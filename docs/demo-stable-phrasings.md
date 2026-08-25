# Demo phrasings — what actually survives the live path

Rewritten 2026-08-25. **This file previously asserted a certification the live path
does not deliver.** It said 48 of 51 phrasings were stable at n>=3. That number was real
and measured — and it measured `resolved_verb` in a harness that hardcodes the subject
and never calls `/resolve`. The live path earns the subject first, then needs a fillable
slot, then needs a bound archetype, then needs a renderer. Four gates. The old file
checked one.

> A question passes when a CARD RENDERS WITH CONTENT. Anything short of that is
> inference wearing certification's clothes.

## The four gates

| gate | what fails it | measured |
|---|---|---|
| 1. subject resolves to the class the verb is typed against | "show me the cost curve" -> Site 0.12 | 2026-08-24, `/resolve` |
| 2. the measure takes no unfillable entity slot | `plan_capability_path` needs `capability_id` | Engine P 400 vs 200 |
| 3. the output type has a registered archetype | `FundingGapSet` had none -> KNOWLEDGE_DOCUMENT | registry read |
| 4. a hardened renderer draws it | all five fell to DesignUI | engine-f log |

Gate 4 closed 2026-08-25 (six deterministic arms). Gate 3 closed for funding gap
(`SHORTFALL_GRID`). Gates 1 and 2 are honest limits to script around, not bugs.

---

## TIER 1 — clears gates 1-4 (22 phrasings)

Subject resolves correctly (>=0.86), measure is slot-free, archetype is bound, and the
render path returns `X-Presentation-Path: archetype-hardened` with rows verbatim.

**NOT end-to-end certified.** Each gate was verified with its own instrument; a full
`/interview/stream` run at n>=2 has NOT been completed — the attempts were voided by a
token expiry and a queue deadlock. **The morning owes this tier one end-to-end pass.**


### `maturity_grid` -> MATRIX_GRID  (subject: Capability)
- "capability maturity by site versus target"
- "show me the maturity grid as of FY26-Q4"

### `projects_in` -> INTERVAL_TIMELINE  (subject: Portfolio)
- "what is scheduled by initiative and phase"
- "show me the plan broken out by initiative"

### `show_cost_curve` -> PERIOD_SERIES  (subject: Portfolio)
- "what does spend look like per period"
- "where does spend exceed the cap"
- "which periods breach the funding cap"
- "where are we over budget"
- "capex versus expense, time-phased"
- "split the spend by capex and expense over time"
- "how much of the spend is capital"

### `show_funding_gap` -> SHORTFALL_GRID  (subject: Portfolio)
- "where is funding short by organization"
- "show the funding gap per funding org"
- "where is funding short by initiative"
- "show the funding gap broken out by initiative"
- "which initiative is underfunded"
- "which funding org has committed less than required"

### `show_site_load` -> THRESHOLD_GRID  (subject: Site)
- "which sites are over their change-load threshold"
- "which sites exceed the threshold in FY26-Q4"
- "which sites are overloaded"
- "which sites are affected and when"
- "show change load across the sites"

### The gantt has only two phrasings — no spares

> "what is scheduled by initiative and phase"
> "show me the plan broken out by initiative"

Nothing else in the fixture reaches `INTERVAL_TIMELINE` through a resolving subject.

---

## TIER 2 — WRONG SUBJECT: the verb is unreachable (12)

These resolve confidently to a class the answering verb is not typed against, so the
compat-walk never nominates it. **The system is declining honestly** — the fix is this
file, not the resolver.

| phrasing | wanted | resolved to |
|---|---|---|
| "where are we against where we said we would be" | `maturity_grid` | **Portfolio** |
| "what is happening in FY26-Q3" | `projects_in` | **Capability** |
| "what runs during FY26-Q3" | `projects_in` | **Capability** |
| "what lands in the third quarter of FY26" | `projects_in` | **Capability** |
| "show me the cost curve" | `show_cost_curve` | **Site** |
| "how is the money phased" | `show_cost_curve` | **Site** |
| "who has not put up their share" | `show_funding_gap` | **Site** |
| "which organization is under-committed" | `show_funding_gap` | **Site** |
| "who is short" | `show_funding_gap` | **Capability** |
| "who is taking the hit and when" | `show_site_load` | **BusinessProcess** |
| "what is happening at Site A — Aurora" | `site_schedule` | **Site** |
| "show the schedule for Site A — Aurora" | `site_schedule` | **Site** |

**The pattern is legible.** Chart-name phrasings lose ("cost curve" is not an ontology
noun). Bare time-phrases go to Capability. "Who" questions go to Site or BusinessProcess.
And both `site_schedule` phrasings resolve to `Site` — arguably right — while
`planSchedule` is typed against `Portfolio`: a modelling mismatch, not a resolver miss.

---

## TIER 3 — NEEDS AN ENTITY SLOT (14)

The measure requires an id that nothing can resolve: plan entities ("Wave 1 Cutover",
"Straight-through invoicing") live only in Engine P's in-memory `PlanState` and are
invisible to `/resolve`. **Architecture item, post-demo.** Do not script these.

| phrasing | intent | needs |
|---|---|---|
| "which projects mature Straight-through invoicing and by when" | `capability_path` | `capability_id` |
| "what gets Straight-through invoicing to target" | `capability_path` | `capability_id` |
| "who is doing the work on Straight-through invoicing" | `capability_path` | `capability_id` |
| "what slips if Wave 1 Cutover slips" | `downstream_of` | `project_id` |
| "how does the Financial Close Automation process evolve over time" | `process_evolution` | `process_id` |
| "walk me through the plateaus for Financial Close Automation" | `process_evolution` | `process_id` |
| "where is Financial Close Automation headed" | `process_evolution` | `process_id` |
| "which capabilities enable Supply Chain Visibility" | `process_evolution` | `process_id` |
| "what has to be in place for Supply Chain Visibility to work" | `process_evolution` | `process_id` |
| "what feeds Supply Chain Visibility" | `process_evolution` | `process_id` |
| "where is the Core ERP Platform used" | `tech_footprint` | `tech_id` |
| "show the footprint of the Core ERP Platform" | `tech_footprint` | `tech_id` |
| "what blocks Wave 1 Cutover" | `what_blocks` | `project_id` |
| "what is Wave 1 Cutover waiting on" | `what_blocks` | `project_id` |

---

## Latency, because it belongs beside the phrasings

Measured 2026-08-24/25 on the real UI path: **median 280s execution** (queue wait
excluded), routing ~12s, DesignUI render 31-59s. The dominant cost is the **`analyst`
fallback at 79-195s** — which fires precisely when a question misses the planning path.

> **Every routing fix is also a latency fix.** A question that routes cleanly costs
> ~12s + render; a question that misses costs 79-195 seconds FOR A NON-ANSWER.

Which is the argument for this file: the tiers above are not just correctness
guidance, they are the difference between a fast answer and a slow apology.
