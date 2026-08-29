---
id:         elicitation-ask-disposition
status:     open
owner:      agent
blocked-on:
repo:       invincible-agent
ruled-by:   ADR-0033 (Accepted 2026-08-29, reachability) + its Amendment 2026-08-28; ADR-0032 (menu integrity, one archetype)
code-site:  src/iagent/defs/dynamic_supervisor.py (execute_subtask, after accept_slots), agent_fleet/planning_agent/slots.py, src/iagent_pure/slot_acceptance.py
summary:    THE BUILD PLAN FOR `ask`, scoped and pre-registered before a line of it exists. Trigger is DETERMINISTIC — a spoken-mandatory slot absent after filling — because confidence was tested at n=48 and rejected (correct fills bottom at 0.93, wrong reach 0.96, the one genuine miss scored 0.96). Disposition point is execute_subtask immediately after accept_slots, the one line where the phrase, the verb, the declarations and the accepted slots are all in hand. THE MERGE SEAM IS ALREADY BUILT — `config.slots` already outranks the filler, so a stateless re-route needs no new state and no new lifetime; the card carries the already-accepted slots forward so the re-route is reconstructed, never re-parsed. THREE SCOPING CORRECTIONS FOUND BY READING: (1) `resolveInstance` RESOLVES, it does not ENUMERATE — its contract requires `identifier: str`, and a slot the phrase never filled has no identifier, so the amendment's fourth option source needs a capability capability (2) does not deliver; (2) the corpus's four ask-candidates split across BOTH trigger shapes — H06/E04 are elicitation (zero candidates), E05/H04 are disambiguation (a name WAS spoken) and need the ORIGINAL source #2, not the fourth; (3) period slots declare no permitted values, so `accept_slots` cannot reject a non-period and D05's `window=["this quarter"]` still reaches the engine. RULED 2026-08-29: free text is the honest INTERIM for instance slots — no enumeration surface exists, so enumeration is genuinely impossible today — carried with the attempt recorded (`option_source: none`, reason `no_enumerate_provider`) and a TRIPWIRE expiry: the day an enumerate provider registers for a slot's class, free text for that slot must FAIL. Corrections 1 and 3 filed as their own items ([[enumerate-is-not-resolve]], [[period-slots-declare-no-vocabulary]]); the three-valued requirement is now an acceptance item on [[the-filler-has-no-entity-resolution]]. THE ASK SHIPS BEFORE ITS OPTIONS CAN, and that ordering is the finding. Measured reach of the trigger, re-run against run 3 after 622f3c8: 3 of 48 (was 2) — and the +1 is NOT an improvement, it is the arity collapse observed: H04 went WRONG->MISSED, so it now asks as elicitation (no menu) instead of disambiguation (menu exists). E05 still passes its name through. Two identical situations, two different behaviours. 37 of 48 are structurally immune — the anti-clippy guardrail is a consequence of the declarations, not a tuned threshold.
---

# The `ask` disposition — the build plan, written before the build

**Lane note.** This packet is scope, mechanism and acceptance only. **No code lands from it until
the entity-resolution and coercion fixes land**, because the disposition's entire job is catching
the residue those leave behind, and that residue is not yet characterised. What follows is the
definition of done, pre-registered, so the build starts from evidence rather than from a blank
page — the same posture the slot investigation used, which is the strongest position any feature
here has started from.

**ADR-0033 is Accepted as of 2026-08-29** (reachability, not frequency — see its *Status change*
section). Everything in this packet is build, not ruling. Where the read contradicts a ruling,
that is flagged as a correction, not exercised as discretion.

---

## 1. The disposition point — one line, and it already holds everything

`src/iagent/defs/dynamic_supervisor.py`, `execute_subtask`, immediately after:

```python
accepted = accept_slots(spoken, declared)
for refusal in accepted.refusals: ...log...
# ← THE DISPOSITION POINT. Everything above resolves; everything below dispatches.
payload = { ... }
```

This is the only place in the system where **the phrase, the routed verb, the verb's declarations
and the accepted slots are all simultaneously in hand.** The slot-filler was moved to this hop for
exactly that reason (`[[the-slot-filler-belongs-where-the-verb-is-known]]`); the disposition
inherits the argument unchanged.

`route | ask | abstain` becomes a decision made **here**, on data already computed, and the ask
path returns instead of building `payload`.

> **Not the router.** The router cannot know a slot is missing — no slot was ever declared to it,
> which is why a slot-shaped question surfaces as `NO_VERB_CLASSIFIED` (an information gap, not a
> threshold problem). Placing the disposition at the router would require re-deriving what this
> line already has.

---

## 2. The trigger — deterministic, model-free, and the alternative is closed

> **A slot declared `spoken-mandatory` that is absent from `accepted.slots` → `ask`.**

Read from the declarations (`agent_fleet/planning_agent/slots.py`, derived from
`inspect.signature`, never hand-kept). No model in the loop. No number to tune.

**Confidence was the obvious alternative and it is closed on evidence** —
`[[a-missing-mandatory-slot-is-a-400-not-an-ask]]` proposed it on one observation of `0.0`; the
48-case corpus refuted it (correct fills bottom at **0.93**, wrong reach **0.96**, the single
genuine miss scored **0.96**, four *correct* empties scored **0.00**). The structural reason,
which is why it should not be re-proposed: **confidence reports certainty about the values
produced, never whether everything the question named was produced.** It cannot flag an omission,
and an omission is what `ask` detects. Recorded in the ADR so the next reader finds it there.

### Measured reach, stated now so it cannot be overclaimed later

Applying the trigger to the battery, **re-run against run 3 after the coercion fix landed
(`622f3c8`) so the figure is not stale**:

| | run 2 | run 3 | note |
|---|---|---|---|
| would **ask** | **2** | **3** | `H06`, `E04`, **+`H04`** |
| would **route** (mandatory slot filled) | 9 | 8 | still includes `E05` — filled with a **name** |
| **structurally immune** (no spoken-mandatory slot) | **37** | **37** | the trigger cannot fire |

> ### ⚠ THE +1 IS NOT AN IMPROVEMENT — IT IS THE COLLAPSE, ALREADY OBSERVED
>
> `H04` moved into the ask population by going **WRONG → MISSED**: the filler stopped emitting
> `process_id: "Order to Cash"` and now emits nothing. So the trigger fires — **as elicitation
> (zero candidates), which has no menu**, instead of as disambiguation (a name was spoken, which
> `resolveInstance` could have scored). A menu that already exists was thrown away.
>
> This is exactly the arity collapse flagged as an acceptance item on
> `[[the-filler-has-no-entity-resolution]]`, and it is **observed, not predicted** — one commit
> ahead of the lane it was written for.
>
> **And the two halves of the same shape now disagree**, which is the clearest possible argument
> for the three-valued contract:
>
> | case | phrasing | run 2 | run 3 |
> |---|---|---|---|
> | `E05` | "the ERP Modernization project" | `project_id: "ERP Modernization"` | `project_id: "ERP Modernization project"` — **still passed through, and now worse** |
> | `H04` | "Order to Cash" | `process_id: "Order to Cash"` | **dropped entirely** |
>
> Two structurally identical situations — an entity spoken by name on a mandatory id slot — now
> produce a **pass-through** and a **drop**. The disposition would see one as a route and the other
> as an elicitation, and **neither is right**: both are `unresolved`, and both have candidates.
> Prompt-level rules cannot make this consistent, because the model is being asked to decide
> something only the resolver knows.

**37 of 48 immune by construction** is the anti-clippy guardrail becoming measurable. ADR-0033 #4's
*"a system that asks when it knows is worse than one that guesses when it doesn't"* is not a
threshold to tune here — it is a consequence of only four of fourteen verbs declaring a mandatory
slot at all.

### The guard against `ask` becoming a crutch

`E04` ("what phases feed into P7") is a **filler defect**, not a genuine gap — `P7` is sitting in
the phrasing. An ask there is a safety net catching a miss that should not have happened.

> **Count them separately: `ask_on_absent_from_phrase` vs `ask_on_present_in_phrase`.** The second
> is a filler regression indicator. Folded into one counter, a degrading filler looks like a
> feature getting more use.

---

## 3. Option sources — and the correction the amendment's fourth source needs

ADR-0033 #2, amended, gives four sources. Their real cost, read rather than assumed:

| slot kind | source | reachable today? |
|---|---|---|
| **enum** (`group_by`, `color_by`, `direction`, `kind`) | the declaration's own `values`, read out of the `Literal` | **yes, free** — present in `slots_for()` output now |
| **period** (`window`, `as_of`) | `FISCAL_PERIODS` (8 entries, `agent_fleet/planning_agent/entities.py`) | **the vocabulary exists; the DECLARATION does not carry it** — correction 3, filed as `[[period-slots-declare-no-vocabulary]]` |
| **instance** (`capability_id`, `project_id`, `process_id`, `tech_id`) | enumeration from Engine P | **no** — see correction 1; scoped in `[[enumerate-is-not-resolve]]`. **Free text is the ruled interim**, with the attempt recorded and a tripwire expiry |
| **handle / ceremony** | never spoken, never asked | n/a |

### ⛔ CORRECTION 1 — `resolveInstance` RESOLVES; it does not ENUMERATE

`[[slot-resolution-entities-in-the-resolver-substrate]]`'s capability (2) reads *"Engine P is a
registered `mesh:resolveInstance` provider"* and its enumerability table lists the instance kind's
menu source as *"an Engine P provider — yes, capability (2)"*. **Registering that provider does
not produce a menu.** The contract is:

```python
class ResolveInstanceRequest(BaseModel):
    identifier: str                      # REQUIRED
    query: Optional[str] = None          # advisory only
```

It scores candidates **against a string the user said**. A slot the phrase never filled has no
such string. Calling it with `identifier: ""` is not a design — it is a degenerate call whose
result the segment-specificity gate would reject anyway.

**This is precisely the gap ADR-0033 #2 was written around.** Its three original sources are all
*outputs of a resolution attempt*; the amendment added a fourth for the zero-candidate case and
named its source as *"instances enumerated from the substrate"*. **Enumeration is a distinct verb
from resolution, and the mesh has no such verb.** So:

> **Filed, not fixed:** capability (2) as scoped unblocks the *name→id* cases and does **not**
> unblock the *menu* cases. Two different needs are wearing one capability's name. The instance
> menu needs an **enumerate** capability (`{slot, class_uri} → [{id, label}]`) that is additive to
> the mesh and is not what registering a `resolveInstance` provider gives you.

### The free-text interim — RULED 2026-08-29, with an expiry that is a test rather than an intention

The first draft of this section read *"the domain is enumerable and the capability to expose it is
simply unbuilt, therefore free text stays forbidden"* — which would have blocked the whole
disposition behind `[[enumerate-is-not-resolve]]`.

> **RULED: free text is the honest interim for instance slots, with the attempt recorded.**
> No enumeration surface exists, so enumeration is genuinely impossible **today** — which is the
> condition amended #2's boundary clause names.

**The concern, recorded in one sentence because the clause was written defensively:** ADR-0033 says
free text is permitted *"never because enumeration was not attempted"*, and "nobody has built the
capability yet" is very close to the reading that clause exists to close — every unbuilt capability
can be described as an impossibility if you stand near enough to it.

**So the interim ships with the guardrail that makes it safe, and the guardrail is mechanical:**

1. **The attempt is recorded.** A free-text ask carries `option_source: "none"` plus the reason —
   `no_enumerate_provider` — never a silence. An ask that cannot say why it has no menu is
   indistinguishable from an ask nobody thought about.
2. **THE EXPIRY IS A TRIPWIRE, not a roadmap line.** The same shape as the held-promise graduation
   condition, and for the same reason — a premise that expires should fail a test, not wait on
   someone's memory:
   > **The day an `enumerate` provider registers for a slot's class, free text for that slot must
   > FAIL.** A test asserts it: for every spoken-mandatory slot, if a provider can enumerate its
   > class then `option_source != "none"`.

Without (2) the interim is permanent the moment it works well enough, which is how every temporary
measure in this repo that lacked one became permanent. With it, the boundary re-closes on its own.

`[[enumerate-is-not-resolve]]` carries the converse and completes the argument: once `enumerate`
exists, a provider answering `too_many` / `unsupported` makes the boundary **mechanically
decidable** rather than a judgement call — which is the difference between a boundary and a fudge.

> **Consequence for sequencing, and it is the sharpest fact in this packet:** all four
> spoken-mandatory slots in the system are **instance** kind (`capability_id`, `project_id`,
> `process_id`, `tech_id` — all `type: "str"`). **Not one is an enum or a period.** So the trigger
> is free and every menu it can build today is blocked. The cheap half and the dangerous half have
> swapped places relative to the carry: for the *carry*, enum and period were the cheap majority;
> for the *ask*, they are unreachable by the trigger and the instance kind is the whole population.

### ⛔ CORRECTION 2 — the corpus's four candidates split across BOTH trigger shapes

The amendment's own table distinguishes disambiguation (many candidates) from elicitation (zero).
The four cases sort cleanly, and they do not all need the fourth source:

| case | phrasing | shape | option source | needs |
|---|---|---|---|---|
| `H06` | "what is the capability path" | **elicitation** — nothing was said | fourth (enumerate) | correction 1's capability |
| `E04` | "what phases feed into P7" | **elicitation** — the value was said and missed | fourth (enumerate) | correction 1's capability, *and* it indicts the filler |
| `E05` | "what does the ERP Modernization project depend on" | **disambiguation** — a name WAS spoken | **original #2** (`resolveInstance` top-k) | three-valued resolution |
| `H04` | "how has Order to Cash evolved" | **disambiguation** — a name WAS spoken | **original #2** | three-valued resolution |

`E05` and `H04` need **no new option source at all.** A name was spoken; `resolveInstance` has an
identifier to score; the candidates it returns *are* the menu, which is the ADR's original design
working exactly as written. What they need is for the resolver to **report failure** rather than
pass the name through:

> **Interface requirement on the resolver join, recorded before it is built:** resolution must be
> three-valued — **`resolved` / `unresolved` / `not-attempted`** — never "substitute an id when you
> can, pass the name through when you can't." A silent pass-through is indistinguishable at the
> disposition point from a successful fill, and converts an askable gap into a 422. The vocabulary
> already exists: `instance_match` in `agent_fleet/ontology_service/instance_resolution.py` is
> `exact | fuzzy | mixed | not_specific | empty`, and its authors already fought this exact fight
> (`empty` was split out of `not_specific` so the gate's actions could not hide inside a
> not-found). **Reuse that vocabulary; do not mint a second one.**

Mapped onto ADR-0033 #4's gate, which is keyed on provenance, this needs no new tier invention:

| `instance_match` | disposition |
|---|---|
| `exact` | **route** (never ask — #4's guardrail) |
| `fuzzy` / `mixed` / `not_specific` | **ask** (candidates exist; this is disambiguation) |
| `empty` | **abstain** — the phone book answered cleanly and there is no such thing |
| *(no attempt — slot absent)* | **ask** as `slot-unfilled` (the amendment's declared tier) |

`empty → abstain` is deliberate and is the one row that does **not** ask: offering a menu when the
substrate genuinely holds nothing is offering an empty menu, which fails menu integrity. The
existing `instance_not_found_message()` is already the honest text for it.

### ⛔ CORRECTION 3 — period slots declare no permitted values, so the guard cannot catch a non-period

`slots_for()` reports `window` as `{"type": "list[str]"}` and `as_of` as `{"type": "str"}` — **no
`values` key**, because there is no `Literal` to read them out of. `FISCAL_PERIODS` lives in the
engine, not in the declaration.

Two consequences:

1. **The period menu is not free.** It requires the eight keys to cross into the declaration (or a
   period provider). Cheap — but it is work, and the plan item's table calls it "no".
2. **`accept_slots` cannot reject a non-period today**, which is why `D05`'s
   `window: ["this quarter"]` passes acceptance cleanly and reaches the engine to 422. The
   declarations are the acceptance schema, and for period slots they declare nothing to check
   against.

**Filed, not fixed** (it is a declaration-layer change, out of this lane's fences). Note it does
*not* block the ask disposition — `window` is spoken-**optional** and never triggers an ask.

---

## 4. Pending-state mechanics — the registered lean, and the code fact that settles it

> **Registered lean: STATELESS RE-ROUTE for v1.** Offered to be argued against; the read
> **strengthened** it, so it stands.

### The measured basis

Census of all fourteen planning verbs, read live from `slots_for()`:

| fact | value |
|---|---|
| verbs declaring a spoken-mandatory slot | **4** (`plan_capability_path`, `plan_dependency_neighborhood`, `plan_process_evolution`, `plan_tech_footprint`) |
| **maximum spoken-mandatory slots on any one verb** | **1** |
| verbs where multi-slot elicitation could arise | **0** |
| the one multi-parameter ceremony (`plan_commit_scenario`) | **not an elicitation candidate at all** — every parameter arrives by a governed UI flow; asking a user to speak them is asking them to compose a governance record in a sentence |

**At most one ask per dispatch, by construction of the current declarations.** Held-promise exists
to hold a partially-filled parse across several asks. That population is **zero**, and building for
a population of zero is how an unowned lifetime is born — which is the vault's TTL questions
arriving in a new costume, and this repo has already paid for that once.

### The graduation condition — a tripwire, not a phase

> **Held-promise earns its place the day a verb declares TWO spoken-mandatory slots.** That is
> mechanically detectable: a test over `slots_for()` across every registered measure, asserting
> `max(mandatory_count) == 1`, failing with *"multi-slot elicitation has arrived — re-open the
> pending-state choice"*. Not a roadmap item anyone must remember; a test that fails when the
> premise expires.

### THE MERGE SEAM IS ALREADY BUILT — and this is what makes the lean cheap rather than merely simple

`execute_subtask` already reads:

```python
spoken = dict(config.slots or {})
declared = predicate.get("slots")
if not spoken and declared:
    spoken = _fill_slots_from_query(...)
```

`config.slots` **already outranks the filler** — *"a caller that supplies slots explicitly is not
overridden by a model."* The answered value therefore rides back in on a field that already exists
and already has the correct precedence. **No new state, no new lifetime, no expiry semantics.** A
re-route *is* a route: every existing guard, including `accept_slots`, applies unchanged.

### The one sharp edge, and the card is what dulls it

That condition is `if not spoken` — **pre-binding one slot suppresses filling of the others.**
Re-routing `plan_dependency_neighborhood` with `config.slots = {"project_id": "P7"}` alone would
skip the filler and silently lose `direction` and `kind`, which the first turn had already filled
correctly. **The answered slot must merge with the accepted ones, not replace them.**

> **So the ask card carries `accepted.slots` forward, and the re-route re-issues
> `config.slots = {**accepted.slots, answered_slot: chosen_value}`.**

This needs **no change to that condition** — the card supplies the whole set. And it buys a
correctness property beyond convenience: the re-route makes **no second model call**, so the second
turn cannot parse the phrase differently than the first did. The re-route is *reconstructed*, never
*re-parsed*. That is the plan item's *"what the ask card carries back so the re-route is
reconstructable rather than re-parsed"* — answered, and answered by a constraint rather than a
preference.

### What the card carries

| field | why |
|---|---|
| `verb_iri`, `sub_query` (verbatim) | the re-route's subject; never re-classified |
| `slot` — name, type, kind | what is being asked for |
| `options[]` — `{value, label}` | the menu; **every entry must route** (#2) |
| `accepted_slots` | the merge, per the sharp edge above |
| `disposition_reason` — `slot-unfilled` \| the `instance_match` tier | audit, and #4's per-tier declaration |

`options[]` empty is **not** a card — it is an abstain. Menu integrity is checked at construction,
not at render.

---

## 5. ACCEPTANCE, PRE-REGISTERED — the build is done when this goes green

Written 2026-08-29, before any implementation exists. Three sections, and **the negative section is
the one that keeps the feature from becoming chatty** — it is not a footnote.

### 5a. MUST ASK

| # | case | phrasing | slot | shape | option source | gated on |
|---|---|---|---|---|---|---|
| A1 | `H06` | "what is the capability path" | `capability_id` | elicitation | enumerate (correction 1) | the enumerate capability |
| A2 | `E04` | "what phases feed into P7" | `project_id` | elicitation | enumerate | same; **also** counted as `ask_on_present_in_phrase` |
| A3 | `E05` | "what does the ERP Modernization project depend on" | `project_id` | disambiguation | `resolveInstance` top-k | three-valued resolution |
| A4 | `H04` | "how has Order to Cash evolved" | `process_id` | disambiguation | `resolveInstance` top-k | three-valued resolution |
| A5 | — | "what phases does I1-P1 depend on upstream" (the live 400) | `project_id` | either | whichever fires | **must not 400** — assert on the disposition, not the text |

**A5's assertion is on the disposition**, because a 400 whose *message* improved is still a 400.
Green when the response is an ask card, never when the error string reads better.

**A3/A4 have a second assertion, and it is the one that can rot:** the ask must fire **because
resolution reported `not_specific`/`fuzzy`**, not because the slot was absent. If the resolver
passes the name through and something downstream notices the id is unknown, the ask fires for the
wrong reason and would stop firing the moment the id shape changes. **Assert on the reported
`instance_match`, not on the absence of a value** — the neighbour-assertion trap.

### 5b. MUST STILL ROUTE SILENTLY — the #4 guardrail, and the correction the dispatch needs

> The dispatch framed this as *"every CORRECT case in the corpus must still route silently."*
> **That is off by one, and the exception is instructive.** `H06` grades **CORRECT** in the filler's
> corpus (`expect: {}`, `got: {}` — the filler was right not to invent a capability) **and must
> ask.** Filler-correct and disposition-complete are different predicates.
>
> **Worth keeping, because it names the seam `ask` occupies: the filler's job is to NOT INVENT;
> the disposition's job is to NOTICE WHAT IS ABSENT.** A case can pass one and fail the other, and
> `H06` is that case — the phrasing named no capability and the verb requires one, so the honest
> empty fill and the unanswerable dispatch are both true at once. Neither component is wrong; the
> behaviour between them was missing. The corrected rule:

| assertion | n |
|---|---|
| every CORRECT case **except `H06`** routes with no card | **39 of 40** |
| every case on a verb with no spoken-mandatory slot routes | **37 of 48**, structurally |
| no ask fires on a **spoken-optional** slot, ever, at any confidence | all — an absent optional is a *default*, which is the answer, not a gap |
| `E06` ("forwards" → `direction: downstream`) still routes | it is a **coercion** defect; the disposition must not paper over it |
| `D05` ("this quarter" → `window: ["this quarter"]`) still routes | `window` is optional; correction 3 is its fix, not this |

`E06` and `D05` are load-bearing negatives. Both are wrong answers the ask disposition **must not
catch**, because catching them would mean asking about optional slots — the chatty failure the
guardrail exists to prevent. **A feature that fixes bugs outside its remit has the wrong trigger.**

### 5c. MUST STILL ABSTAIN — and this row is UNMEASURED, stated rather than assumed

`ask` is a **third** disposition, not a replacement for the second. Whatever reaches
`NO_VERB_CLASSIFIED` for non-slot reasons must still abstain.

> **The corpus cannot supply this row.** Every one of its 48 cases *supplies the verb* — it measures
> the filler given a correct route, never the route. So the abstain-preservation assertion needs a
> **different instrument**: the routing corpus, run before and after, asserting the abstain set is
> unchanged.
>
> Recorded as a gap rather than filled with a corpus that cannot answer it. A suite that both
> produces and checks its own artifact is vacuous, and so is one asserting on a neighbour of the
> claim.

One row this section *does* own: **`instance_match == "empty"` must abstain, not ask** (§3,
correction 2). The phone book answered cleanly; there is nothing to offer.

---

## 6. The two non-slot consumers — scoped, not built

Three consumers, three trigger shapes, **one disposition**. That the disposition is shared is the
argument for building it once at the funnel rather than three times at three call sites.

| consumer | trigger | options come from | menu integrity | new substrate? |
|---|---|---|---|---|
| **slot elicitation** | `spoken-mandatory` absent after filling | declarations + enumeration | every option is a legal value | **yes** — the enumerate capability |
| **duplicate canvas** | a seed phrase matches an existing canvas | **the user's own canvas list** | *open existing* and *seed new* are both real actions | **none** |
| **instance disambiguation** | `instance_match ∈ {fuzzy, mixed, not_specific}` | `resolveInstance` candidates | candidates are routable by construction | **none** — needs a per-case threshold ruling |

### Duplicate canvas — the cheapest of the three, and the best first proof

Seeding the same phrase three times produced **three** Portfolio Planning canvases. `recomputes:
false` working as designed: a seed answer records an act.

> *"You already have a Portfolio Planning canvas — open it, or seed a new one?"*

Two options, both routable, **zero provider work**. It is a stronger demonstration of the amended
#2's fourth source than the slot picker is, because the slot picker's menu is blocked on correction
1 and this one's is not. **Recommended as the disposition's first live consumer** — it proves the
mechanism end-to-end while the enumerate capability is still being built.

Interim remains duplicates-plus-manual-delete: a visible cost, taken over a silent guess.

### Instance disambiguation thresholds — a ruling this packet does not make

The triage found abstention (`not_specific`) firing on **19 candidates** *and* on **exactly 1** —
simultaneously too strict and too loose. The prior question is *what abstention is for*: refusing
to guess, or refusing to ask? Those imply different numbers, and **only one of them is compatible
with a picker.**

Now that `ask` exists as a disposition, the answer is available in a way it was not before:
**abstention is for refusing to guess; asking is what replaces refusing-to-ask.** So the 19-candidate
case becomes an ask (with top-k, not all 19 — the menu has a length bound worth ruling) and the
1-candidate case becomes… a confirmation, or a route, and that one still needs a human ruling.
Filed as a decision this packet raises and does not take.

---

## 7. The archetype constraint — DEFERRING THE SURFACE, deliberately and on the record

ADR-0033 is explicit, and it predicted the exact failure:

> *"They must be built as **one archetype** (the elicitation card), not two components. Absent this
> sentence, two agents build them separately and the citizenship grammar forks at its first
> extension."*

The amendment adds that a slot picker is *"exactly the third agent that would fork it."*

**This lane takes the second option the constraint allows, and says so plainly:**

> **The elicitation SURFACE is DEFERRED. The backend disposition lands first.** The surface is a
> separate, **jointly designed** item with the cortex lane — ADR-0032's goal-shape card and this
> card are one archetype, and one archetype is designed once, by one design, with both consumers in
> the room.

This is not a scheduling convenience; it is the constraint's own compliance path. The alternative —
building a card here and reconciling later — is the fork the ADR names, and reconciliation after
the fact has never once been cheaper than designing together.

**What the backend ships in the meantime is a disposition, not a component:** a typed
`ask` result at the disposition point, carrying the fields in §4, rendered by whatever the honest
fallback is until the archetype exists. Per the registered-or-honest-fallback rule
(`[[triage-card-archetype]]`), an unregistered kind **must degrade visibly, never borrow another
species' affordances** — which is precisely how the triage card shipped Approve/Reject on a
failure. An ask rendered as an abstain card would be that same bug, second edition.

> **Coordination owed, not optional:** before the surface item opens, the cortex lane must be in
> the room. This packet's §4 field list is the backend's half of that conversation and is offered
> as input to the joint design, **not as a card schema**.

---

## 8. Fences this lane observed

- **No code.** Scope, mechanism, acceptance, status.
- **No funnel edits** — the disposition point is *named*, not touched.
- **Nothing touching engine-p** — the enumerate gap was found by reading `resolveInstance`'s
  request model, not by changing anything.
- **Defects found in shared scope were filed, not fixed:** correction 1 (capability (2) does not
  deliver enumeration), correction 3 (period slots declare no permitted values). Both are
  cross-referenced from `[[slot-resolution-entities-in-the-resolver-substrate]]`'s territory and
  belong to whoever owns the declaration layer.

## 9. Build order, once the fences lift

1. **The trigger** — deterministic, `option_source: "none"` with the reason recorded, free text as
   the ruled interim (§3). Green: **A5 stops being a 400.** Proves the disposition point without
   needing any option source at all.
2. **The duplicate-canvas consumer** — zero substrate work, a **real** menu, end-to-end proof of
   the whole shape while the enumerate capability is still being built.
3. **Three-valued resolution** (`[[the-filler-has-no-entity-resolution]]`, now an acceptance item
   there) → A3/A4 go green on the **original** #2 option source. **No new substrate.**
4. **The enumerate capability** (`[[enumerate-is-not-resolve]]`) → A1/A2 go green, the fourth
   option source becomes real, and **the free-text tripwire fires**, closing the interim.

Steps 1 and 2 need nothing that does not exist. Step 3 is Lane 1's, already written into its
packet. Step 4 is this lane's own next scoping question.

> **The ask ships before its options can, and that ordering is the finding — not a compromise.**
> The trigger reads declarations; the menu needs a substrate capability nobody has built. Those are
> independent, and discovering it now is what lets step 1 ship on its own instead of waiting behind
> step 4.
