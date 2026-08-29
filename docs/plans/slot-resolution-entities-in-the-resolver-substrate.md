---
id:         slot-resolution-entities-in-the-resolver-substrate
status:     open
owner:
blocked-on:
repo:       invincible-agent
code-site:  agent_fleet/ontology_service/instance_resolution.py, agent_fleet/planning_agent/entity_resolution.py
ruled-by:   ADR-0033 (interrogative disambiguation) + its Amendment 2026-08-28; ADR-0031 (resolution ladder)
summary:    THE USERS' QUESTIONS ARE THE SPEC — the system meets it when the spoken parameter reaches the verb. PLATFORM, not finance. Capability (1) is THREE JOINS: declare (missing, crosses into iagent-mesh), extract (EXISTS in BAML), carry (missing — the supervisor drops what BAML extracted). Measured: 12 of 14 planning verbs take parameters, 0 declare them, and 3 of 4 certified parameterised phrasings deliver the wrong scope today — one on the seeded board. Elicitation is ALREADY RULED (ADR-0033 + Amendment 2026-08-28). Three consumers already need one missing capability — entities as resolvable instances in the resolver substrate. Four planning verbs are unreachable from natural language today (Tier 3, "do not script these"); the triage's instance-resolution abstentions are unruled; and Engine F (ADR-0045) is blocked entirely on it. FIRST PLATFORM ITEM AFTER THE CANVAS CHAIN CLOSES — it unblocks four existing verbs, one whole engine, and every future slot-heavy domain, which is the ordering argument and the item's whole justification.
---

# The users' questions are the spec; the system meets it when the spoken parameter reaches the verb

**Headline updated 2026-08-28**, after the census and baseline. The original framing —
"entities are not resolvable instances, and three consumers are waiting" — undersold this by
scoping it to four unreachable verbs plus Engine F. That was a **corpus fact wearing a capability
fact's clothes**: the certified questions route because they are the versions whose defaults
happen to be right.

**Measured since:** twelve of fourteen planning verbs accept parameters; **zero** can declare them;
and BAML extracts them while the dispatch payload drops them
(`[[slots-are-extracted-then-dropped-at-dispatch]]`). Three of four certified parameterised
phrasings deliver the wrong scope today, one of them on the seeded board.

So this is not a prerequisite Engine F happens to share. **It is the planning engine's own
unfinished half** — and the ends are built while the middle is missing.

**This is platform work that finance happens to need first.** It is written as its own item, not
folded into ADR-0045, precisely because two of its three consumers are not finance — and an item
buried inside a finance ADR is invisible to them.

## The finding, consolidated — three consumers, one missing capability

All three are already in the record. Cited, not restated.

### 1. Four planning verbs are unreachable from natural language

`docs/demo-stable-phrasings.md`, **Tier 3 — needs an entity slot**, fourteen phrasings across
four intents (`capability_path`, `downstream_of`, `process_evolution`, `tech_footprint`,
`what_blocks`). Its own words:

> The measure requires an id that nothing can resolve: plan entities ("Wave 1 Cutover",
> "Straight-through invoicing") live only in Engine P's in-memory `PlanState` and are invisible
> to `/resolve`. **Architecture item, post-demo. Do not script these.**

These verbs are built, typed, registered and correct. They cannot be *asked*.

### 2. The triage's instance-resolution abstentions are unruled

Two findings, and they point in **opposite directions**:

* abstention (`not_specific`) on **19 candidates** — arguably right, arguably a threshold that
  gives up where a picker should ask
* abstention on **exactly 1 candidate** — much harder to defend, and the clearer signal that the
  thresholds are not tuned to any stated intent

> **The thresholds are currently both too strict and too loose**, which is what "needs a ruling"
> means here — not "pick a number", but "decide what abstention is FOR".

### 3. Engine F is blocked entirely (ADR-0045 §7)

Its flagship question carries an instance slot (`project #######`), and four of its six verbs take
an entity. Building the engine first means building six verbs that route to `NO_VERB_CLASSIFIED`.

**Three consumers, one capability: entities as resolvable instances in the resolver substrate.**

## Design questions this item must ANSWER — deliberately not answered here

These need measurement, not ruling-in-advance. Scoping them is this item's job; deciding them
before anyone has looked is how a design becomes a guess with a document.

### How do entities register?

At engine registration? At data ingest? Somewhere else?

> **Cautionary precedent: `[[seeder-manufactures-declarations]]`.** Registration with side effects
> is a shape this repo has already been bitten by — a component that *declares* something as a
> byproduct of doing something else, so the declaration's lifetime is tied to an unrelated event.
> Whatever mechanism is chosen, the question "what happens to these entities when the engine
> restarts / the data is re-ingested / the scenario is discarded" must be answered **in the
> design**, not discovered.

Note the sharpest version of the problem, from consumer 1: Engine P's entities live in an
**in-memory** store that a pod restart empties. An entity registry populated from it inherits that
lifetime unless something is decided about it.

### How does instance resolution compose with the compat-walk?

Today the walk is `subClassOf*0..5` over graph edges, from a resolved **class**. An instance is
not a class. Does resolving an instance pin the class and then walk? Does it bypass the walk? What
happens when the instance's class has no verbs but its parent does — and note the graph is
currently **flat** (`[[handback-the-graph-taxonomy-is-flat-by-design]]`), so a walk from an
instance's class reaches nothing today.

### What should the abstention thresholds be?

Per the triage's evidence that they are simultaneously too strict and too loose. The prior
question is **what abstention is for**: refusing to guess, or refusing to ask? Those imply
different thresholds, and only one of them is compatible with a picker.

### How do slot-filling failures surface? — ALREADY RULED. Do not re-decide it.

**ADR-0033 governs this**, and the search that found it is the reason this section is short: a
second elicitation ruling was nearly written before anyone checked. `route | ask | abstain` is
decided, options come from a governed vocabulary and never from the model, one bounded turn, and
best-effort-at-low-confidence is retired as policy.

Its **Amendment 2026-08-28** brings the zero-candidate case inside two commitments that were
written against disambiguation:

* **#2 gains a fourth option source** — the verb's **registered slot inventory** plus substrate
  enumeration. Free text **only** where the substrate genuinely cannot enumerate; never as a
  default, and never because enumeration was not attempted.
* **#4 declares `slot-unfilled` → ask** — a missing slot has no `resolved_via`, so the gate had no
  disposition for it and would have failed at policy load.

**What is left for this item is BUILD, not ruling.** Two inherited constraints, both binding:

> **Ask only below the same thresholds that gate disambiguation.** ADR-0033 #4: *"a system that
> asks when it knows is worse than one that guesses when it doesn't."* A slot that filled cleanly
> is never asked about.

> **ONE elicitation archetype, not two.** ADR-0033 and ADR-0032's goal-shape card share the
> surface and the menu-integrity rule. The ADR predicted the failure in as many words — *"absent
> this sentence, two agents build them separately and the citizenship grammar forks at its first
> extension"* — and a slot picker is exactly the third agent that would fork it.

Still true and still this item's: a slot failure must be legible as **itself**, not as
`NO_VERB_CLASSIFIED`, which is what the operator sees today and which sends the diagnosis to the
wrong component.

### A SECOND live consumer for the `ask` disposition — duplicate canvases

Filed 2026-08-28, from the seeding chain's first end-to-end run: seeding the phrase three times
produced **three Portfolio Planning canvases**. That is `recomputes: false` working as designed —
a seed answer records an act, so re-asking mints a new board rather than refreshing one.

**The fix is not dedupe.** Silent dedupe guesses that the user meant the existing board; silent
duplication litters. Both decide something the user could be asked:

> **"You already have a Portfolio Planning canvas — open it, or seed a new one?"**

This is ADR-0033's amended `ask` with a second live consumer, and it is an unusually clean one:
**the options come from the user's own canvas list** — enumerable, governed, and every option
routes (opening an existing canvas and seeding a new one are both real actions). Menu-integrity
holds without any new substrate, which makes it a stronger case for the amended #2's fourth
option source than the slot picker itself: no provider work is needed to enumerate it.

**Interim, honestly:** duplicates plus manual delete. That is a real cost and it is visible, which
is the trade this project takes over a silent guess.

### Pending-state mechanics — a CHOICE between two named designs, not a blank page

ADR-0033's *Scope: decision vs build* already sketched both, and deferred the choice deliberately:

> the **supervisor's pending-state mechanics** — stateless re-route with the clarified subject
> substituted (simplest v1) vs. a held-promise the way grouped reviews hold suspended promises.

**Registered lean, offered to be argued against: STATELESS RE-ROUTE for v1.**

The reasoning is that it introduces no new lifetime. A re-route **is** a route: every existing
guard applies unchanged, nothing persists between turns, and there is no expiry semantics to get
wrong. The held-promise design adds a suspended state with a lifetime — which is the vault's TTL
questions arriving in a new costume, and this repo has spent a week learning what an unowned
lifetime costs.

**The graduation condition, named now so the choice is revisited on evidence rather than taste:**

> **Held-promise earns its place when MULTI-SLOT elicitation arrives.** One ask per missing slot
> makes stateless re-routing chatty — three missing slots become three full round trips, and
> ADR-0033 bounds a single exchange at one turn (two for goal-shaped). At that point the promise
> is holding a partially-filled parse across several asks, which is what it is for.

Until then the open build questions are narrow: **where the clarified value is substituted** (the
supervisor re-issues the original phrase with the slot bound, or the funnel accepts a pre-bound
slot), and **what the ask card carries back** so the re-route is reconstructable rather than
re-parsed.

## Why this is first after the canvas chain

**The ordering argument IS the justification**, and it belongs where the board shows it:

* unblocks **four existing planning verbs** that are already built and unreachable
* unblocks **Engine F entirely** — one engine, six verbs, ADR-0045
* unblocks **every future slot-heavy domain** — sprint planning is the named next copy, and it
  will have the same shape

Nothing else queued has three consumers waiting on it. Every domain engine after this one either
needs it or is deliberately entity-free, and the second is a narrow class.

## ACCEPTANCE, PRE-REGISTERED — the test plan precedes the build

Written 2026-08-28, before any implementation exists. **The build is done when this table goes
green**, and each capability has its own green condition so a partial landing is visible as
partial rather than reported as done.

### Capability (1) — the three joins, in dependency order

| # | join | green when | measured how |
|---|---|---|---|
| 1a | **declare** | `register_engine_to_mesh()` accepts slots, and `planCapabilityPath`'s graph edge carries a slot declaration with its kind | the graph query that found zero — re-run, expect non-zero |
| 1b | **carry** | the supervisor's dispatch payload contains extracted params, and Engine P's `req.params` arrives non-empty | the payload enumeration in `[[slots-are-extracted-then-dropped-at-dispatch]]`, re-read |
| 1c | **extract** | already true — BAML classes on the live path | no work; guard against regression |

**Slot kinds, from the census, so the distinction that nearly corrupted it is unexpressible as an
error in the schema:** `spoken-mandatory | spoken-optional | handle | ceremony`.

### The four-row acceptance table — the baseline, INVERTED

Each row is a measured failure today. Each becomes a passing assertion.

| # | question | today (measured) | green when |
|---|---|---|---|
| 1 | "where is funding short **by initiative**" | 11 **organisations** (`group_by=org`) | returns **initiatives** |
| 2 | "maturity grid **as of FY26-Q4**" | unfiltered, latest per cell | cells assessed **at or before** that date |
| 3 | "sites exceed threshold **in FY26-Q4**" | **four** quarters | **one** period |
| 4 | "the plan **broken out by initiative**" | passes — `initiative` **is the default** | passes **because the parameter ARRIVED** |

> ### ROW 4 IS LOAD-BEARING AND IS THE ONLY ONE THAT CAN FAIL SILENTLY
>
> Rows 1–3 go green when the carry works. **Row 4 is already green and proves nothing** — it
> passes today by coincidence of default, and would keep passing if the carry were never built.
>
> So row 4's assertion is not on the ANSWER, it is on the ARRIVAL: the test must observe that
> `group_by` reached the verb, not that the output grouped by initiative. Assert on the delivered
> parameter — `req.params`, or a recorded `delivered_slots` — never on the rows alone.
>
> **This is the certification gap in miniature.** Routes-and-renders certified row 4 and would
> certify it again; only delivered-versus-spoken tells a working carry from a lucky default. A
> suite that omits row 4's arrival check is measuring the defaults, exactly as the last one did.

### Capability (2) — instance resolution

| green when | note |
|---|---|
| Engine P is a registered `mesh:resolveInstance` provider with `domains: ["PORTFOLIO_PLANNING"]` | the mechanism EXISTS and is federated — four providers precede it (Task 3) |
| `/resolve` fans out to it and returns plan entities as candidates | provider-agnostic by construction, ~30s cache |
| "what blocks Wave 1 Cutover" reaches `plan_dependency_neighborhood` with `project_id` filled | one of the four spoken-mandatory verbs |

**No entity registry, and no lifecycle hazard.** Nothing is declared into a store; the provider
answers live from its own state. `PlanStore` emptying on restart is then correct behaviour rather
than staleness — there is no registry to go bad.

### Enumerability is NOT one question — three of four kinds are already free

| kind | source of the ask-menu | needs work? |
|---|---|---|
| **enum** (`group_by`, `color_by`) | the signature's own `Literal` | **no** |
| **period** (`window`, `as_of`) | `FISCAL_PERIODS` | **no** |
| **instance** (`project_id`, `capability_id`, …) | an Engine P provider | yes — capability (2) |
| **handle** (`baseline_state`, `ops`) | never spoken | n/a |

**The dangerous half is the cheap half.** The silent-drop population — the seven verbs whose
spoken parameters are dropped without any disclosure surface — is dominated by `enum` and
`period` slots, both enumerable today with no substrate work. Capability (2) is needed for the
four *visible* failures; capability (1) alone fixes the seven *invisible* ones.

## What this item is NOT

**Not a finance feature.** Finance is the third consumer to arrive, not the reason.

**Not a resolver rewrite.** The resolver works; class resolution is measured at high confidence on
the Tier-1 corpus. What is missing is a *kind* of thing it can resolve.

**Not blocked on Engine F.** The dependency runs the other way, and ADR-0045 records it as a hard
block in its own frontmatter.
