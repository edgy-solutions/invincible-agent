# ADR-0045 — Engine F: finance verbs over standard ontologies

**Status:** Accepted (2026-08-28). **Build sequencing: post-planning-engine.** Nothing here starts
until the canvas chain closes, and §7's blocker lands before any verb is written.
**Date:** 2026-08-28
**Deciders:** Architect
**Blocked-on:** plan item `[[slot-resolution-entities-in-the-resolver-substrate]]` — see §7. This is
a hard block, not a preference: Engine F's flagship question carries an instance slot, and building
six verbs before the slot picker exists means building six verbs that route to
`NO_VERB_CLASSIFIED`.
**Related:**
  - [ADR-0035](ADR-0035-two-planes-process-and-data-with-embedded-provenance.md) — the two planes.
    This ADR is that ruling applied a second time: it is what decides Engine F is a new engine
    rather than verbs bolted onto Engine P.
  - [ADR-0044](ADR-0044-routing-ticket-credentials-minted-per-request.md) — routing tickets minted
    per request. Engine F is its **first consumer proof on the per-user path** (§5).
  - [ADR-0042](ADR-0042-live-view-artifacts-recomputing-cards-on-the-one-presentation-path.md) —
    live views. Finance answers are live views by the same test; none of them is a record of an act.
  - `portfolio_planning_extension.ttl` — the ontology-extension pattern this copies exactly.

---

## Context

The finance group's work is currently answered by hand: variance analysis, estimates at
completion, burn rates, funding status. The questions are stable, the methods are public, and the
data lives in datasets rather than in anything a workshop authors.

The planning engine (Engine P) exists and works. The tempting move is to add finance verbs to it.
This ADR refuses that, and records why — plus the ontology choices that make the refusal
sustainable rather than merely tidy.

---

## Decision 1 — A NEW ENGINE, not verbs in Engine P

**Engine F is a separate engine.** The two-planes ruling (ADR-0035) decides it, and the boundary
is already drawn twice in this fleet:

| engine | owns | plane |
|---|---|---|
| Engine P | plan state **born in the workshop** — scenarios, ops, the commit ceremony | process |
| Engine DA | analysis over **datasets** the mesh governs | data |
| **Engine F** | analysis over **financial data** — actuals, EACs, control accounts | **data** |

**Finance analysis is governed READING, not plan mutation.** An EAC is computed from actuals that
already exist; it does not author a scenario, it cannot be dragged, and committing it means
nothing. Engine P's whole surface — `fork`, `append_op`, `commit`, the in-memory `PlanStore` — is
machinery for state that a room *creates*. None of it applies.

Putting finance verbs in Engine P would give one engine two planes, and the first thing that
breaks is the ceremony: `plan_commit_scenario` writes baseline from a scenario, and there is no
coherent answer to what "committing" a variance analysis would mean.

**Same boundary as Engine P vs Engine DA**, decided the same way, for the third time.

## Decision 2 — Standard ontologies, three layers

Local invention is refused at every layer where a standard exists.

**PROV-O backbone.** Finance classes hang off `prov:Entity`, identical to
`portfolio_planning_extension`'s pattern. Not a new root, not a parallel hierarchy.

> **Note for the implementer, learned 2026-08-28:** the ingest does **not** materialise a
> `subClassOf` edge to a `prov:` target — no such edge exists anywhere in the graph today,
> including under `mesh:Archetype` and `mesh:Response`. Finance classes will therefore be **flat**
> in Neo4j exactly as the planning classes are. That is the current design, not a defect to fix
> here; see `[[handback-the-graph-taxonomy-is-flat-by-design]]`.

**IPMDAR as the domain vocabulary.** Control account, work package, WBS/OBS, earned value
technique, time-phased BCWS/BCWP/ACWP. Two reasons, and the second is the durable one:

1. **Analysts' natural phrasing resolves without translation.** "What's the variance on control
   account 3.1.2" is already the vocabulary; a locally-invented synonym set would need a
   translation layer that exists only to undo an avoidable choice.
2. **Future interchange maps field-for-field.** If this ever reads a real program system, IPMDAR
   is the format that system already speaks. A local vocabulary makes that a migration; the
   standard makes it a mapping.

**FIBO for money primitives** — monetary amount, currency — rather than local inventions. This is
the units law applied to finance: a number without a declared unit is not an amount, and `value_unit`
already exists on the planning side for exactly this reason. FIBO supplies the primitive so the
question "dollars or thousands of dollars" is answered by the model rather than by convention.

## Decision 3 — Six verbs, deterministic, each with its archetype

Every verb is deterministic and typed, per ADR-0030 (one verb, one fixed output type). None
generates prose; each returns rows an existing archetype draws.

| verb | shape | archetype |
|---|---|---|
| `fin_variance_analysis` | the recursive playbook — decompose, drill drivers, recurse until explained | (to be typed; likely a nested set) |
| `fin_eac_calculation` | estimate at completion, **method mandatory** — see below | period series or single measure |
| `fin_performance_indices` | CPI/SPI over time | `PERIOD_SERIES` |
| `fin_burn_rate` | spend rate against plan | `PERIOD_SERIES` |
| `fin_variance_drivers` | ranked contributors to a variance | `INSTANCES_BY_PROPERTY` |
| `fin_funding_status` | authorized / obligated / expended | **`SHORTFALL_GRID`** |

> ### ⛔ THE ARCHETYPE COLUMN ABOVE IS SUPERSEDED — see the Amendment 2026-08-29
>
> It was written before any payload existed, and the payload read found **three of the six
> assignments wrong**. `fin_variance_drivers` → `INSTANCES_BY_PROPERTY` is **refused**;
> `fin_eac_calculation` fits neither of its two suggestions; `fin_variance_analysis`'s deferral
> is confirmed. **Two rows survive as binding rows** (`fin_burn_rate`, `fin_funding_status`) and
> one carries an open question. The governing fact — *only seven archetypes have a projection
> arm, so anything else is not a binding row whatever the vocabulary says* — is at the head of
> the amendment. **Do not act on this column.**
>
> The shape/verb columns stand. Only the archetype column moved.

**`fin_variance_analysis` is ONE verb, not a chain.** The recursive playbook — decompose the
variance, drill into drivers, recurse until explained — is many SQL steps and one *question*. It
stays one verb because the caller asks one thing; the recursion is the verb's implementation, not
the caller's problem.

**`fin_funding_status` needs no new archetype.** `SHORTFALL_GRID` already asks *how far below what
is owed*, with three quantities per cell (required / committed / secured). Authorized / obligated /
expended maps nearly field-for-field. **Reuse it.** Minting a fourth grid archetype whose colour
means the same thing is precisely what the grid-splitting ruling refused.

### `fin_eac_calculation` — METHOD IS A MANDATORY SLOT, NEVER A DEFAULT

This is designed behaviour and it must be written into the verb, not left to the caller's
discipline.

The EAC formulas **disagree materially** — a CPI-based EAC and a CPI×SPI-based EAC on the same
program can differ by a margin that changes decisions. There is no defensible default, because
choosing one silently is choosing an answer.

**A bare "what's the EAC" is REFUSED, with the refusal naming the choice:** *"which method — CPI,
CPI×SPI, or remaining-work-at-budget?"* That is the honest-refusal pattern the planning engine
already uses (`NotInModel`, the source-size gate, `check_rationale`), applied where the cost of
guessing is a number someone will repeat in a meeting.

> This is the `[[the-cost-of-guessing-is-a-mutation]]` law one layer out. There the cost of a
> guess was an unrequested write; here it is an unrequested **assertion**. Both are worse than a
> question.

## Decision 4 — Notional data, obviously notional

Fake program names, round numbers, public-methodology formulas only.

**Nothing from the finance group's actual work enters this repository.** Not as a fixture, not as
a test case, not as an example in a docstring. The boundary is deliberate and this ADR states it
so that no later contributor has to infer it from absence.

Notional data must also be **obviously** notional — round numbers and plainly invented names — so
that a screenshot cannot be mistaken for real program data by someone who did not author it.

## Decision 5 — Reads through the mesh with minted tickets

Engine F reads through the mesh and takes a **per-request minted ticket** (ADR-0044). It holds no
standing credential and no connection string of its own.

**Engine F is ADR-0044's first consumer proof on the per-user path.** That ADR's mechanism has
been built and reasoned about; Engine F is where it is exercised by a second consumer with a
different data shape. If the ticket mechanism has a gap for per-user narrowing, this is where it
surfaces — which is a reason to sequence Engine F *after* the mechanism settles, not before.

## Decision 6 — This is a TEMPLATE, and the pattern is stamped

The shape is now repeatable, and naming it is half the point of this ADR:

> **domain ontology extension + typed deterministic verbs + existing archetypes + mesh reads**

Engine P proved it. Engine F copies it. **Sprint planning is the next candidate copy** — same
shape, different vocabulary, and it should be built by pointing at this ADR rather than by
rediscovering the pattern.

What makes it a template rather than a coincidence: each layer is chosen from a standard where
one exists, each verb is typed and deterministic, no archetype is minted that an existing one
already serves, and the engine reads rather than owns.

## Decision 7 — BLOCKED-ON: slot resolution

Engine F's flagship question — *"what's the variance on project #######"* — carries an **instance
slot**. Today that slot cannot be filled: plan and program entities are not resolvable instances
in the resolver substrate, so the question routes to `NO_VERB_CLASSIFIED` no matter how good the
verb is.

**This blocks the whole engine, not one verb.** Four of Engine F's six take an entity.

The platform item is `[[slot-resolution-entities-in-the-resolver-substrate]]`. It is deliberately
**not** part of this ADR: it is platform work that finance happens to need first, it already has
three consumers, and burying it inside a finance ADR would hide it from the two that are not
finance.

---

## Consequences

**Good.** A second engine on a proven pattern, with vocabulary an analyst already speaks and a
path to real-system interchange that is a mapping rather than a migration. `SHORTFALL_GRID` gets a
second consumer, which is the test of whether it was genuinely generic.

**Costs.** A third engine to deploy, register and keep re-registered — and this fleet has now
demonstrated three separate ways an engine can be present but unrouted. Engine F's bring-up should
verify registration **in the graph**, never at `/health`.

**Deferred.** `fin_variance_analysis`'s archetype is not chosen here; it needs a payload read
first, per the discipline that decided every other binding in this fleet.

## Indicators we got this wrong

- An analyst has to translate their question into non-IPMDAR words to get an answer.
- `fin_eac_calculation` acquires a default method "for convenience".
- A finance verb needs to write plan state — which would mean the two-planes boundary was drawn in
  the wrong place.
- A fourth grid archetype appears whose colour means *deficit*.

---

## Amendment 2026-08-29 — the payload read is done, and Decision 3's archetype column was optimistic

**Ruled by the architect 2026-08-29**, on the binding table produced before cortex was
dispatched (`[[engine-f-archetype-bindings]]`). **Decisions 1–7 stand unchanged.** What changes
is the *archetype* column of Decision 3's table, which was written before any payload existed
and turns out to have been three-sixths wrong.

### THE STRUCTURAL FACT THAT GOVERNS ALL THREE RULINGS

**Only seven archetypes have a projection arm** — `INTERVAL_TIMELINE`, `PERIOD_SERIES`,
`THRESHOLD_GRID`, `MATRIX_GRID`, `DELTA_SET`, `CANVAS_SEED`, `SHORTFALL_GRID`
(`_PLANNING_ARCHETYPES`, `agent_fleet/presentation_agent/main.py`). **Anything else is not a
binding row, whatever the archetype vocabulary says.**

That collapses a vocabulary question into a code question, and it is the same shape as
`canvas_type needs a reader before a producer`: **an archetype name existing somewhere is not
an archetype existing.** `KNOWN_ARCHETYPES` is an admission vocabulary; the projection arm is
the thing that draws.

### What the read actually found

| verb | Decision 3 said | the read says |
|---|---|---|
| `fin_burn_rate` | `PERIOD_SERIES` | ✅ **binding row**, clean |
| `fin_funding_status` | `SHORTFALL_GRID` | ✅ **binding row**, via a dual-vocabulary accommodation |
| `fin_performance_indices` | `PERIOD_SERIES` | ✅ **binding row + one open question** to cortex |
| `fin_variance_drivers` | `INSTANCES_BY_PROPERTY` | ❌ **refused** — build |
| `fin_eac_calculation` | "period series or single measure" | ❌ **neither** — build |
| `fin_variance_analysis` | "(to be typed; likely a nested set)" | ❌ **deferral confirmed** — build or flatten |

**`SHORTFALL_GRID` got its second consumer and it held**, which was the stated test of whether
it was genuinely generic. Recorded as a success, because the other half of this amendment is
three failures and the reuse ruling should not be read as discredited by them.

---

### Ruling 1 — `fin_eac_calculation`: a small deterministic archetype. NOT `ASSET_STATE_METRIC`.

**Build this first. It is the smallest and the need is the clearest.**

`ASSET_STATE_METRIC` is refused on two independent grounds:

1. **It is outside the projection arm** and dispatches to `b.RenderAsMetric` — **an LLM
   renderer**, the exact path the deterministic arm exists to bypass. Measured costs of that
   path: *31–59s per card* and *portfolio funding figures sent to a fallback chain whose first
   entry is OpenRouter.* Sending program cost forecasts down it is the wrong default for the
   real data Decision 5 contemplates this engine eventually reading.
2. **The stronger argument:** a card drawing `14,152,381` without *"CPI-based, EAC = BAC / CPI"*
   beside it **undoes at the card the refusal the router just enforced.** The whole point of the
   mandatory method slot is that the number is meaningless without its method; a renderer that
   drops the method re-creates the ambiguity one layer later, and does it *after* the user has
   been made to choose. That is worse than never having asked.

**The build:** a deterministic single-measure archetype carrying **value + method + formula**.
The method field is non-negotiable — it is what distinguishes this from every existing metric
card, and it is the reason a generic one cannot be reused.

`PERIOD_SERIES` is separately wrong: one row, and **no `period` field at all** (`as_of_period`
is a stamp, not an axis). A series component drawing a single point with no axis is a chart of
nothing.

### Ruling 2 — `fin_variance_drivers`: `INSTANCES_BY_PROPERTY` is REFUSED. A ranked-set archetype is the build.

Two reasons, **and the second is the disqualifying one**:

1. **Schema mismatch.** `INSTANCES_BY_PROPERTY` is *"a table of INSTANCES of class C in domain
   D, FILTERED by property P"* and requires `target.filter_property`, `state_vocabulary`, and
   `columns[].from` pointing at ontology properties. A ranking has **no filter property**, **no
   enumerable value set** (contribution is continuous), and its magnitudes are **computed**
   rather than properties of the instance.
2. **It is hand-fed by a BFF feeder that hard-sets its own archetype**
   (`src/iagent/gateway.py`, `instances_by_property_dashboard`), and the comment beside it
   already names copying that as *re-opening `archetype-chosen-before-data` at the BFF, one hop
   from where it was closed*. **A precedent whose own code warns against being copied is a
   precedent to leave alone.**

And the fit fails at the semantic level rather than the field level: **`rows[]` order is not
meaningful there, and order IS the answer here.**

#### `DELTA_SET` was checked before minting, per the ruling. It does NOT generalize.

| | `DELTA_SET` (`plan_diff`) | a driver ranking |
|---|---|---|
| axis | **N metrics**, one comparison | **one metric**, N entities |
| ordering | unordered — a set, "the price beside the benefit" | **ordering is the answer** |
| share of a whole | none | `share_of_total`, and the tail must be visible |
| magnitude | a **producer-formatted display STRING** (`"-$1.2M in FY26-Q1"`) | a raw signed number + `value_unit` |

**The axis is inverted**, which is not a field that can be added. But the *cell grammar* is
genuinely close — `delta` (signed), `direction` (improved/degraded), `affected` (named things)
map onto `contribution`, `favourable`, `entity_name`. **Reuse the cell vocabulary, not the
archetype**, so the two read as one system without pretending one is the other.

> **Caution carried into that build:** `DELTA_SET`'s `magnitude` is a display string the
> *producer* formats. Engine F emits raw numbers plus `value_unit` and leaves formatting to the
> renderer. A ranked-set archetype should not copy the string habit — a producer formatting
> display text is a presentation decision at the producer, which is the boundary ADR-0042 §2
> draws.

**Owed on this ruling landing:** `fin_variance_drivers` currently emits `instance_id`,
`instance_label`, `property_label` and `value` on every row. Those were written against an
*assumption* of `INSTANCES_BY_PROPERTY`'s shape rather than its schema, they are harmless
duplicates of `entity_id` / `entity_name` / `contribution`, and **they are removed when the
ranked-set decision lands.** They are not evidence of a fit and the packet says so.

### Ruling 3 — `fin_variance_analysis`: deferral CONFIRMED, and the open question is stated

The deferral in Decision 3 (*"needs a payload read first"*) was correct and this **is** that
read. The finding: it emits **one row containing a tree** (nested `contributors`, plus
`stop_reason` per node and a `residual` for the sub-materiality tail), and **every archetype in
the arm is flat** — `rows` is an array the projector passes through verbatim. Nothing consumes
nesting. A grid or series component handed this draws one row with an unreadable nested cell:
the shape of failure that looks like it worked.

**Two candidate designs, and they are not refinements of each other:**

* **(a) A recursive/hierarchical archetype** — a real component build with its own contract.
  Renders the nesting, the per-node `stop_reason`, and the residual.
* **(b) Flatten at the engine** — the verb returns its top level plus a **drill-down
  affordance**, and *"drill into CA 3.1"* becomes a follow-on question.

**The architect's lean is (b)**, on two grounds: it is closer to how the analysis is actually
consumed in a meeting, and **it composes with the elicitation surface instead of requiring a new
one** — which is the archetype-unity constraint ADR-0033 defends, arriving from the other side.

**This is a design call for this ADR, not a binding decision, and it is deliberately left
open here.** Choosing (b) changes what the verb RETURNS, which is a change to Decision 3's
"one verb, not a chain" ruling and must be argued as such rather than slipped in as a
rendering convenience. **Nothing is built for either until that is settled.**

---

### Consequence, stated plainly so nobody reads this as a blocker

**Nothing here blocks the finance engine's routing.** All six verbs route, refuse and return
rows correctly today. What is blocked is **three of six cards DRAWING** — and until the builds
land, those three answers reach the user through the degraded path rather than as their
intended cards. That is a known state with a named cause, not a regression.

**Two binding rows go to cortex now**, with the page-load step and the
`KNOWN_ARCHETYPES`-before-advertisement ordering trap
(`docs/runbooks/adding-an-engine.md` §9 step 6). **The three builds are sequenced above**: EAC
metric, then ranked-set, then the variance tree behind its design question.

### Indicators this amendment got it wrong

- A ranked-set archetype is minted that `DELTA_SET` could have served after all — meaning the
  axis-inversion argument above was wrong and should have been tested by building rather than
  by reading.
- The EAC card ships without its method, for convenience, on the grounds that the router
  already asked.
- `fin_variance_analysis` is flattened at the engine **and** a hierarchical archetype is built
  anyway — which would mean (a) and (b) were treated as refinements after all.
