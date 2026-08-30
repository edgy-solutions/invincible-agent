---
id:         elicitation-ask-disposition
status:     open
owner:      agent
blocked-on:
repo:       invincible-agent
ruled-by:   ADR-0033 (Accepted 2026-08-29, reachability) + its Amendment 2026-08-28; ADR-0032 (menu integrity, one archetype)
code-site:  src/iagent/defs/dynamic_supervisor.py (execute_subtask, after accept_slots), agent_fleet/planning_agent/slots.py, src/iagent_pure/slot_acceptance.py
summary:    BUILT 2026-08-29 (f6c066a). `src/iagent_pure/slot_disposition.py`, wired at the disposition point in execute_subtask; 28 acceptance tests green. TRIGGER is deterministic and model-free — a spoken-mandatory slot absent after filling, plus the tri-state outcomes — because confidence was tested at n=48 and REJECTED (correct fills bottom 0.93, wrong reach 0.96, the one genuine miss 0.96, four CORRECT empties 0.00; it reports certainty about values produced, never whether everything named was produced). GUARDRAIL IS STRUCTURAL, NOT TUNED: the walk visits only spoken-mandatory declarations, so of run 5's three residual misses it fires on exactly ONE (E05, mandatory) and E04/C04 are unreachable by construction — both GENUINE misses of information the user supplied, both must route, because a feature that catches all the residue has the wrong trigger. THE BUILD CORRECTED THE PLAN: a retained cross-class candidate is EVIDENCE, not an OPTION. `wrong_class` is by definition an outcome whose candidate's class is not the slot's referent, so the filter preserving menu integrity removes exactly the candidate that was kept — offering I1 for project_id gives a 422 with the user's own click behind it. It becomes context instead ("I found 'ERP Modernization', but that is not one"). CONSEQUENCE, NOT GLOSSED: BOTH live ask cases fall to free text today, and the disambiguation path is built and correct with NO live corpus case reaching it — fixture-tested, and the test says so, because coverage of a built path is not evidence of a measured one. CRITICAL PATH IS THE ROUTER-SIDE ENUMERATE FAN-OUT, routed to the option-source lane: Engine P registered as a mesh:enumerateInstances provider and nothing in Engine O dispatches an enumerate — A REGISTRATION IS NOT A REACHABLE CALL ([[a-registration-is-not-a-reachable-call]]). Wired as ENUMERATE_INSTANCES_URL, unset, reporting free_text_reason `no_provider` rather than silence; one env var closes it. THE FREE-TEXT TRIPWIRE WAS WRONG AS FIRST WRITTEN and is corrected in place: it is on SILENCE, not on absence of a provider, since at menu bound 8 a registered provider legitimately answers `too_many` for Capability's 9 members. SURFACE STILL DEFERRED — a typed `slot_elicitation` status plus prose that stands alone, never a second card; one archetype with ADR-0032's, per the fork the ADR predicted.
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

## ✅ BUILT 2026-08-29 — and the build found one thing the plan had wrong

`src/iagent_pure/slot_disposition.py` (pure, injected enumerator), wired at the disposition
point in `execute_subtask`, with the pre-registered acceptance as
`tests/routing/test_slot_disposition.py` — **28 tests, green.** The trigger, the guardrail,
the abstain row, both tripwires and the card contract are all asserted.

### ⛔ THE CORRECTION: a retained cross-class candidate is EVIDENCE, not an OPTION

This packet said `E05` was *"disambiguation, candidate `I1` retained, a real menu, unblocked
today."* **It is not a menu, and the reason is structural rather than incidental.**

`wrong_class` is *by definition* an outcome whose candidate's class is **not** the slot's
referent — that is what the word means. So the class filter that keeps ADR-0033 #2's
menu-integrity rule intact removes **exactly the candidate that was kept**:

    E05  project_id (declares #Project)  <-  candidate I1, class #Initiative
         offering I1 => plan_dependency_neighborhood(project_id="I1") => 422

That is the same 422 the entire tri-state exists to prevent, now with the user's own click
behind it. **A `wrong_class` outcome can never supply a menu for its own slot.**

`/fill_slots` synthesises that candidate deliberately — *"so every non-empty outcome carries
at least the candidate it found"* — and the synthesis is right; only the assumption about
what it is for was wrong. It is **context**, and the disposition now says it out loud:

> *"Which project? I found 'ERP Modernization', but that is not one. There are 14 to choose
> from. Too many to list — name it and I will run this."*

The user was understood, and they named another species. Saying so is strictly better than
either a 422 or a bare "which project?".

### What this changes about the picture, honestly

**Both** live ask cases fall to free text today, not one:

| | shape | menu | why |
|---|---|---|---|
| `H06` `capability_id` | elicitation | **no** | `no_provider` — no router-side fan-out exists |
| `E05` `project_id` | disambiguation | **no** | candidate is cross-class; `Project` is 14 > bound 8 → `too_many` |

So the disambiguation path is **built and correct with no live corpus case reaching it**. It
is exercised by fixture (`test_same_class_candidates_ARE_a_menu`) and that is stated in the
test rather than hidden — coverage of a built path, not evidence of a measured one.

**And the critical path is now unambiguous: the router-side enumerate fan-out.** Engine P
registered as a `mesh:enumerateInstances` provider, but **nothing in Engine O dispatches an
enumerate** the way `/resolve` fans out a resolve. A registration is not a reachable call, and
the supervisor must not invent a provider's URL — the phantom-service-URL shape. So the wiring
is `ENUMERATE_INSTANCES_URL`, unset, and the disposition reports `no_provider` rather than
staying silent. **One env var is the whole connection when the fan-out lands.**

### The free-text tripwire, corrected as it was written

The packet's expiry read *"the day an enumerate provider registers for a slot's class, free
text for that slot must FAIL."* **That is wrong as stated**, and the landed capability is what
showed it: at menu bound 8, `Capability` (9 members) legitimately answers `too_many`, so a
registered provider can correctly produce a menuless ask.

> **The tripwire is on SILENCE, not on absence of a provider.** An ask with no menu must name
> its reason from a closed set — `too_many | unsupported | no_provider | no_referent`. A
> menuless ask that cannot say why is the open question ADR-0033 retired, wearing a slot's
> name. `test_TRIPWIRE_free_text_must_carry_a_provider_reason` asserts exactly that, across
> all four enumerator behaviours including an outcome nobody has declared yet.

### Two things deliberately not built

**The surface.** ADR-0033's archetype-unity constraint holds: this ships a typed
`status: "slot_elicitation"` result plus honest prose that stands on its own, not a card
component. The card is one archetype with ADR-0032's, designed once with cortex in the room.

**The re-route's second turn.** The card carries `accepted_slots` so `{**accepted, slot:
chosen}` reconstructs rather than re-parses — the mechanism is asserted by test — but nothing
consumes the answer yet, because the surface that would collect it is deferred.

### A seal updated rather than weakened

`test_the_supervisor_degrades_to_defaults_on_every_failure_path` counted bare `return {}`
statements; the helper now returns `_FillResult(slots, resolution)` so the disposition can see
*why* a referent slot is missing. The seal follows the type: it accepts
`_FillResult({}, {})` — **both** args empty, since a failure returning a non-empty resolution
would be asserting knowledge it does not have.

### Pre-existing failures, checked and not adopted

The full suite has 6 failures, none from this change and none touching its surface: two
dangling `docs/` citations (`cortex-data-client.md`, `jupyter_guide.md`) from three unrelated
SDK/broker packets, three endpoint-gating manifest rows (`/internal/identity/redeem`,
`/fill_slots`, `/enumerate_instances` + `/resolve_instance`), and a helm chart-version drift.
**`/enumerate_instances` and `/fill_slots` are the option-source lane's routes** — filed here,
not fixed, per the split.

## OWNERSHIP, settled 2026-08-29 — two lanes were pointed at one build

The filler lane's "fix (3)" and this packet's disposition are **the same build**, and both lanes
arrived at it at the same moment. Split, so neither starts it twice:

| | owns | why |
|---|---|---|
| **this lane** | the **`ask` disposition** — trigger, disposition point, card contract, re-route, the two non-slot consumers | it holds the ADR (Accepted, wake condition cited), the mechanism plan, the pre-registered acceptance and the trigger design |
| **the filler lane** | the **option source** — `[[enumerate-is-not-resolve]]`, plus the harness gap in §2b | the filler, resolver and battery are the surface this disposition *consumes*; the enumerate provider is squarely that territory |

> **The split keeps the producer and the consumer of the tri-state in different hands**, which is
> what caught the arity collapse in the first place — one lane shipped a change that silently
> removed the other's menu, and it was visible only because a second reader was holding the
> consumer's requirements. Merging the lanes would remove that check exactly when the contract
> between them is newest.

**Handoff, concretely:** fix (3) transfers here with its current state; `[[enumerate-is-not-resolve]]`
and the battery's `outcome`/`candidates` recording transfer there. Neither lane is blocked on the
other for its first step.

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

> **Not the router** — *for this trigger.* The router cannot know a slot is missing, because no
> slot was ever declared to it, which is why a slot-shaped question surfaces as
> `NO_VERB_CLASSIFIED` (an information gap, not a threshold problem). Placing **slot** elicitation
> at the router would require re-deriving what this line already has.

> ### ⛔ BOUNDED 2026-08-29 — "the only place" is true of THIS TRIGGER, not of the disposition
>
> The paragraph above claims this line is *"the only place where the phrase, the routed verb, the
> declarations and the accepted slots are all simultaneously in hand."* That is correct, and it is
> an argument about **trigger #1 (missing slot)** and **#2 (ambiguous instance)** — both of which
> fire **after** verb selection.
>
> **ADR-0033's Addendum adds a #3 that fires BEFORE it.** An ambiguous subject *class*
> (`[[ipmdar-reuses-names-across-hierarchies]]`) is undetermined at subject resolution — upstream
> of `/classify_predicate`, where **there is no verb yet**. Its options are classes, not members,
> and each implies a *different verb*. So it cannot be served from this line: `predicate` does not
> exist here in the sense #3 needs, and a build that tries will discover that the hard way.
>
> **One disposition, one card, TWO TRIGGER SITES.** The vocabulary, the menu-integrity rule, the
> one-turn bound and the card contract are shared; the *point of decision* is not. Recording it
> here because §1's argument reads, unbounded, as a claim about the whole disposition — and the
> next reader would take it as one.

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

Applying the trigger to the battery. **RE-RUN AGAINST RUN 5** — fix (1) landed, so the earlier
figures are superseded rather than merely aged:

| | run 2 | run 3 | **run 5** | note |
|---|---|---|---|---|
| would **ask** | 2 | 3 | **2** | now `H06`, **`E05`** — `E04` has left the population |
| would **route** (mandatory slot filled) | 9 | 8 | **9** | |
| **structurally immune** (no spoken-mandatory slot) | 37 | 37 | **37** | invariant, as designed |

### The residue is characterised, and `ask` catches exactly the right third of it

Run 5's residue is **3 MISSED, 0 WRONG, 0 EXTRA**. Partitioned by the kind of slot missed:

| case | misses | kind | disposition |
|---|---|---|---|
| **`E05`** "the ERP Modernization **project**" | `project_id` | **spoken-mandatory** | **ASK** |
| `E04` "what phases feed into P7" | `direction` | spoken-optional | **route** — a default is the answer |
| `C04` "site S1 in FY26-Q2" | `site_id`, `window` | spoken-optional | **route** — and it is the flaky one |

**The trigger fires on one of the three and correctly declines the other two.** That is the
guardrail behaving, not a coverage gap: an absent optional is a *default*, which is an answer, and
asking about it is the chatty failure ADR-0033 #4 exists to prevent.

> ### `E04` LEFT THE ASK POPULATION, AND IT LEFT FOR THE RIGHT REASON
>
> In run 2 `E04` missed all three slots including mandatory `project_id`, and was the strongest
> reachability citation in the ADR's status change. In run 5 it fills `project_id: P7` and
> `kind: phase`, missing only `direction`. **The filler fixed it, which is what should have
> happened** — the ask was a safety net for a miss that should not have occurred, and the net is
> now unneeded for that case.
>
> The `ask_on_present_in_phrase` counter (below) is exactly the instrument that would have shown
> this, and it validates keeping it: a shrinking ask population *because the filler improved* is
> the success mode, and it must be distinguishable from a shrinking one because the trigger broke.
>
> **The ADR's citation is unaffected.** `E04` was cited as measured evidence that the class was
> unreachable at the time of the status change, and it was. A fix landing afterwards does not
> un-fire a wake condition — and `E05` and `H06` still stand under it.

### THE TWO REMAINING CASES ARE A MINIMAL PAIR — one of each shape

| | `H06` "what is the capability path" | `E05` "the ERP Modernization **project**" |
|---|---|---|
| shape | **elicitation** — nothing was said | **disambiguation** — a name was said |
| candidates | none | **retained** (resolved `I1`, an `Initiative`, against a `#Project` slot) |
| option source | free-text interim (§3) | the candidate — a **real menu**, for the first time |
| blocked on | `[[enumerate-is-not-resolve]]` | **nothing** |

One case per shape, and one of them is fully unblocked. That is a better starting position than
this packet was parked with, and it is the tri-state contract paying for itself immediately.

> **`E05`'s corpus expectation is unsatisfiable and is not this build's problem.** No project bears
> that name, so `project_id: P1` cannot be produced by any correct resolver; the accuracy packet
> already flags it as a probable authoring error. The *disposition* assertion is unaffected — it
> asks about `project_id` and offers `I1`, and whether the corpus's `expect` is right is a corpus
> question.

## ⛔ 2b. THE INSTRUMENT CANNOT CHECK THE ASSERTION IT WAS GIVEN — found by re-running

The pre-registered acceptance says, for `E05`-shaped cases: *"assert on the reported
`instance_match`, not on the absence of a value — the neighbour-assertion trap."*

**The battery cannot do that today.** Every record in `slot-fill-battery-run5.json` carries exactly
`id, cls, conf, expect, got, flags, phrasing`. **No outcome. No candidates.** So from the run data
alone:

```
H06  got: {}      <- elicitation, no candidates
E05  got: {}      <- disambiguation, candidate I1 retained
```

**The two are indistinguishable in the file.** The tri-state exists on the `/fill_slots` wire and in
the measurement's prose; it does not reach the artifact any test would read. A partition computed
from this file has to *guess* which shape each empty is, which is precisely the neighbour-assertion
trap arriving in the instrument instead of in a test.

> **Prerequisite, and it is small: the battery must record `outcome` and `candidates` per slot.**
> Until it does, the pre-registered A3/A4 assertions are unverifiable and any green they report is
> vacuous. This is the same failure the four-row table's row 4 was written against — *only
> delivered-versus-spoken tells a working carry from a lucky default* — one layer up.

**Filed against the harness, which is Lane 1's** (`scripts/slot_fill_battery.py`), and named here
because this lane is its consumer and would otherwise discover it mid-build.

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

**Re-registered against run 5.** The rows are fewer and better: fix (1) resolved `H04`, `C05`,
`C06` and `D04` outright, and fix (2) resolved `E04`'s mandatory slot — so the table now names only
cases that are *still* residue, plus the structural one.

| # | case | phrasing | slot | shape | option source | gated on |
|---|---|---|---|---|---|---|
| A1 | `H06` | "what is the capability path" | `capability_id` | **elicitation** | free-text interim → enumerate | nothing (interim ships); `[[enumerate-is-not-resolve]]` for the menu |
| A2 | `E05` | "what does the ERP Modernization **project** depend on" | `project_id` | **disambiguation** | **the retained candidate (`I1`)** | **nothing — unblocked today** |
| A3 | — | "what phases does I1-P1 depend on upstream" (the live 400) | `project_id` | either | whichever fires | **must not 400** — assert on the disposition, not the text |

**A3's assertion is on the disposition**, because a 400 whose *message* improved is still a 400.
Green when the response is an ask card, never when the error string reads better.

**A2 carries the assertion the instrument cannot yet check** (§2b): the ask must fire **because the
fill reported `wrong_class` with a candidate**, not because the value happens to be absent. Assert
on the reported outcome — `H06` and `E05` are both `got: {}`, and a test that keys on emptiness
passes for both while meaning neither. **A2 is blocked on the harness recording `outcome`, not on
any substrate.**

> **Retired rows, recorded rather than deleted, because a shrinking acceptance table is a claim.**
> `E04` (mandatory slot now filled — the filler fixed it) and `H04` (now resolves `BP1` cleanly) are
> **no longer ask cases**. They move to §5b as must-route-silently, which is a stronger assertion
> than they carried before: they must now *stay* fixed.

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

| assertion | n (run 5) |
|---|---|
| every CORRECT case **except `H06`** routes with no card | **44 of 45** |
| every case on a verb with no spoken-mandatory slot routes | **37 of 48**, structurally |
| no ask fires on a **spoken-optional** slot, ever, at any confidence | all — an absent optional is a *default*, which is the answer, not a gap |
| **`E04`** (misses `direction` only) routes | **spoken-optional** — a default IS the answer. The strongest negative in the table: `E04` was an ask case two runs ago and must not be one now |
| **`C04`** (misses `site_id`, `window`) routes | both optional — **and it is the known flaky case**, so an ask here would make non-determinism user-visible as a question |
| `E06` ("forwards") and `D05` ("this quarter") still route | both **fixed** by fix (2) and both on optional slots; recorded so the disposition is never credited with them |

**`E04` and `C04` are the load-bearing negatives now**, and they are stronger than the pair they
replace. Both are *genuine misses* — real information the user supplied that the filler did not
capture — and the disposition **must still not ask**, because both misses are on optional slots
where a default is a legitimate answer. A trigger that reached them would be asking about things
the system can proceed without.

> **This is the sharpest statement of the guardrail available: `ask` must decline two of the three
> remaining misses in the corpus.** A feature that catches all the residue has the wrong trigger.

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

## 6. The non-slot consumers — scoped, not built

**Updated 2026-08-29: FOUR consumers, not three.** ADR-0033's Addendum adds an ambiguous-subject-
class trigger, and it is the first one that does **not** share this build's disposition point —
see the bound on §1. That the *disposition* is shared is still the argument for building it once
rather than four times; that the *trigger site* is not shared is the thing a reader must not
assume.

| consumer | fires | trigger | options come from | menu integrity | new substrate? |
|---|---|---|---|---|---|
| **slot elicitation** (#1) | **after** verb selection | `spoken-mandatory` absent after filling | declarations + enumeration | every option is a legal value | the enumerate fan-out |
| **instance disambiguation** (#2) | **after** verb selection | `instance_match ∈ {fuzzy, mixed, not_specific}` | `resolveInstance` candidates | candidates routable by construction | **none** — needs a per-case threshold ruling |
| **subject-class ambiguity** (#3) | **BEFORE** verb selection | two classes tied at 1.0 on one name | **classes** from the graph | each class **is** a registered verb's `input_uri` | **none** — but a **second trigger site** |
| **duplicate canvas** | outside the slot path entirely | a seed phrase matches an existing canvas | the user's own canvas list | *open existing* / *seed new* are both real actions | **none** |

> **#3 is the one that breaks the pattern the other three share.** Its options are *classes*, each
> implying a **different verb** — so it is not an under-specified slot, it is a question whose verb
> is undetermined. *"The variance on Integration and Test"* ties `fin:ControlAccount`
> (`finVarianceDrivers`) against `fin:WBSElement`, and the honest card asks **what kind of thing
> was meant**, never a list of members.
>
> **Evidence-wise it is the weakest of the four and its own packet says so** — one witnessed
> occurrence, notional seed, undeployed engine. What raises it is **structural, not frequency**:
> IPMDAR reuses names across hierarchies *by design*, so it arrives with the first real-system
> read rather than accumulating. Recorded that way rather than counted with the measured ones.
>
> **Not this build's, and deliberately not started.** Its two candidate designs — clarify the class
> vs. filter candidates to the slot's referent — are not refinements of each other, so picking one
> before a live case is a guess with a document. It waits for fix (3) to settle.

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
3. ~~**Three-valued resolution**~~ — **DONE** (fix (1), run 5). The contract is live, WRONG is
   eliminated 5 → 0, and `E05` arrives as `wrong_class` **with its candidate retained**. This step
   moved from a dependency to an asset while the packet was parked, which is why **A2 is unblocked
   today** and why the disambiguation half no longer waits on anything.
4. **The enumerate capability** (`[[enumerate-is-not-resolve]]`) → A1/A2 go green, the fourth
   option source becomes real, and **the free-text tripwire fires**, closing the interim.

Steps 1, 2 and 3 need nothing that does not exist — **step 3 already landed.** Step 4 is the
filler lane's, per the ownership split above. The only true prerequisite left for the
pre-registered acceptance to be *checkable* is the harness recording `outcome` (§2b), which is
small and also theirs.

> **The ask ships before its options can, and that ordering is the finding — not a compromise.**
> The trigger reads declarations; the menu needs a substrate capability nobody has built. Those are
> independent, and discovering it now is what lets step 1 ship on its own instead of waiting behind
> step 4.
