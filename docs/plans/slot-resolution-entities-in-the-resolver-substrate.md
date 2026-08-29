---
id:         slot-resolution-entities-in-the-resolver-substrate
status:     open
owner:
blocked-on:
repo:       invincible-agent
code-site:  agent_fleet/ontology_service/instance_resolution.py, agent_fleet/planning_agent/entity_resolution.py
ruled-by:   ADR-0033 (interrogative disambiguation) + its Amendment 2026-08-28; ADR-0031 (resolution ladder)
summary:    PLATFORM, not finance. Elicitation is ALREADY RULED (ADR-0033 + Amendment 2026-08-28) — this item is the RESOLUTION capability plus build. Three consumers already need one missing capability — entities as resolvable instances in the resolver substrate. Four planning verbs are unreachable from natural language today (Tier 3, "do not script these"); the triage's instance-resolution abstentions are unruled; and Engine F (ADR-0045) is blocked entirely on it. FIRST PLATFORM ITEM AFTER THE CANVAS CHAIN CLOSES — it unblocks four existing verbs, one whole engine, and every future slot-heavy domain, which is the ordering argument and the item's whole justification.
---

# Entities are not resolvable instances, and three consumers are waiting

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

## What this item is NOT

**Not a finance feature.** Finance is the third consumer to arrive, not the reason.

**Not a resolver rewrite.** The resolver works; class resolution is measured at high confidence on
the Tier-1 corpus. What is missing is a *kind* of thing it can resolve.

**Not blocked on Engine F.** The dependency runs the other way, and ADR-0045 records it as a hard
block in its own frontmatter.
