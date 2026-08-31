---
id:         enumerate-is-not-resolve
status:     open
owner:      agent
blocked-on:
repo:       invincible-agent
ruled-by:   ADR-0033 Amendment 2026-08-28 (#2's fourth option source) — this item is the SCOPING of the capability that clause assumes
code-site:  agent_fleet/datahub_wrapper/main.py (the mesh:resolveInstance registration, as the shape to copy), agent_fleet/ontology_service/instance_resolution.py, agent_fleet/utils/mesh_registration.py
summary:    PROVIDER DONE (3516103), CALLER MISSING — now the single item gating both live ask cases. Engine P is a registered `mesh:enumerateInstances` provider: minted, ontology-classed, three-outcome (members | too_many | unsupported), correct. NOTHING IN ENGINE O DISPATCHES AN ENUMERATE the way /resolve fans out a resolve, so the supervisor cannot reach it — A REGISTRATION IS NOT A REACHABLE CALL ([[a-registration-is-not-a-reachable-call]], instance 2). The disposition ships wired to `ENUMERATE_INSTANCES_URL`, unset, reporting free_text_reason `no_provider` rather than silence, so the gap is visible in logs and assertable in tests and ONE ENV VAR CLOSES IT. REMAINING DELTA IS THE FAN-OUT ONLY — cardinality is ruled (three outcomes, bound 8), the class-vocabulary join is closed (`referent` carries the class URI), lifetime is settled (live from the store, no registry). What is left is a provider-agnostic dispatch in Engine O, copying /resolve. Routed to the option-source lane. MEASURED CONSEQUENCE, and the probe it asked for CORRECTED THE BOUND: ruled at 8 while its own example was "nine capabilities is a menu", now 10, so Capability's 9 IS a menu and H06 gets a real one; Project at 14 still `too_many` — but it DOES give two of the four spoken-mandatory slots real menus (process_id n=2, tech_id n=5), and it converts `no_provider` into a provider-reported reason, which is the difference between a boundary and a fudge.
---

# `enumerate` is not `resolve` — the fourth option source needs a verb the mesh does not have

**Raised 2026-08-29** by the elicitation scoping pass (`[[elicitation-ask-disposition]]`), which
went looking for the menu source ADR-0033's amended #2 promised and found the contract underneath
it answers a different question.

## The finding, in one contract

```python
class ResolveInstanceRequest(BaseModel):
    identifier: str                      # REQUIRED
    query: Optional[str] = None          # full user query, advisory only
```

`mesh:resolveInstance` **scores candidates against a string the user said.** Everything downstream
of it assumes that string exists: the specificity gate is *"a candidate only survives if the
extracted identifier names a whole segment of it"*, and `decide()` keys its whole table on the
identifier's presence.

**A slot the phrase never filled has no such string.** `identifier: ""` is not a design — it is a
degenerate call that the specificity gate would reject on its own terms, and whose result
(`empty`) would be a lie about the substrate rather than a fact about it.

| | `resolve` | `enumerate` |
|---|---|---|
| input | an identifier the user spoke | a **class** the slot declares |
| output | scored candidates, ranked | the members, unranked |
| answers | *"which thing did they mean?"* | *"what things are there?"* |
| exists today | **yes** — federated, 4+ providers | **no** |

## Why this reshapes the roadmap rather than adding a chore

`[[slot-resolution-entities-in-the-resolver-substrate]]`'s capability (2) — *"Engine P is a
registered `mesh:resolveInstance` provider"* — is scoped correctly for the cases it names and its
enumerability table then lists the instance kind's menu source as *"an Engine P provider — yes,
capability (2)."* **Registering that provider does not produce a menu.** Corrected in place there;
the detail lives here.

The consequence orders the elicitation build:

> **All four spoken-mandatory slots in the system are instance-kind** — `capability_id`,
> `project_id`, `process_id`, `tech_id`, every one `type: "str"`. **Not one is an enum. Not one is
> a period.** So the ask *trigger* is free (it reads the declarations) and every *menu* it could
> build is blocked. This is the exact mirror of the carry's position, where enum and period were
> the cheap majority and instance was the visible minority.

So the work splits, and it splits cleanly:

1. **The `ask` disposition ships first**, with the honest interim below.
2. **`E05`/`H04`-shaped cases ship next**, on the **original** #2 option source — a name WAS spoken,
   `resolveInstance` has something to score, and its candidates are the menu. They need
   three-valued resolution (`[[the-filler-has-no-entity-resolution]]`), not this item.
3. **`H06`/`E04`-shaped cases ship last**, when this item lands.

## THE DESIGN QUESTION THIS ITEM OWNS: cardinality, not plumbing

The plumbing is a copy. `register_engine_to_mesh(verb="mesh:enumerateInstances", input_uri=…#InstanceClass,
output_uri=…#InstanceEnumeration, …)` follows Engine D's `resolveInstance` registration line for
line, including `domains`, `provider`, and a per-provider `timeout_s`. That is not the hard part
and should not be mistaken for it.

**The hard part is that `enumerate` has no natural bound.**

| substrate | count | enumerate a DataHub dataset class |
|---|---|---|
| Engine P `Capability` | 9 | — |
| Engine P `Project` | **14** | — |
| Engine P `Initiative` / `BusinessProcess` / `Technology` / `Site` / `Organization` | 3 / 2 / 5 / 4 / 3 | — |
| DataHub | — | **unbounded** |

> **CORRECTED 2026-08-29, measured against the live store rather than recalled.** The first
> draft of this table read *"projects / processes / tech / sites = 3 / 2 / 5 / 4"*. **`Project`
> is 14**; the 3 was `Initiative`. The error mattered: at menu bound 8 it is the difference
> between `project_id` having a menu and answering `too_many`, which is exactly the fact the
> ask disposition depends on.

`resolve` is naturally bounded because a query bounds it; `enumerate` is bounded only by the
substrate. A provider that cannot enumerate its class must be able to **say so**, as a first-class
answer, the same way `resolveInstance` made *"an empty list is a first-class answer"* explicit in
its own description.

> **So the response needs three outcomes, not a list:** `members` (here they are),
> `too_many` (the class is real and larger than any menu — with a count if cheap), and
> `unsupported` (this provider does not enumerate this class).

### AND THIS IS WHAT MAKES ADR-0033'S FREE-TEXT BOUNDARY PRINCIPLED

ADR-0033 permits free text **only** where the substrate *"genuinely cannot enumerate the slot's
domain — never as a default, never as a convenience, and never because enumeration was not
attempted."* Today that clause cannot be evaluated, because there is no attempt to make. Once
`enumerate` exists, it becomes **mechanically decidable**:

| provider says | ask uses |
|---|---|
| `members` | a menu — and free text is **forbidden** |
| `too_many` / `unsupported` | free text, **legitimately**, with the attempt recorded |

That is the difference between a boundary and a fudge. **A slot asked as free text must carry the
provider's own reason** — never a default, never a silence.

## ⚠ REMAINING DELTA 2026-08-29 — the provider is DONE; the CALLER is the whole item now

The disposition shipped (`f6c066a`) and tried to consume this. It could not, and the reason is
narrow enough to be a punch list rather than a design.

**Finished, needing no further thought:**

| question this item raised | answered |
|---|---|
| cardinality — can a provider refuse? | **yes** — `members` / `too_many` / `unsupported`, count on `too_many` |
| menu length bound | **ruled at 8**, a human-attention bound |
| filter in v1? | **no** — `too_many` → free text, not a search box smuggled into a bounded turn |
| lifetime | **live from the store, no registry** — an emptied store answering zero is correct, not stale |
| open question 4, "whose class vocabulary?" | **closed** — `referent` carries the class URI |

**Missing is one hop.** The supervisor deliberately does **not** construct Engine P's URL: that is
the phantom-service-URL shape, and a guessed address fails as a *timeout* rather than as *nobody
built this*.

### The punch list — a copy of the neighbour

1. **A fan-out in Engine O**, provider-agnostic by construction, exactly as `/resolve` fans out
   `mesh:resolveInstance`: look up providers for the verb, call them, per-provider `timeout_s`.
2. **Pass the three outcomes through unflattened.** `unsupported` from one provider and `members`
   from another are different facts; a fan-out returning "no members" for both re-creates the
   collapse this item's design exists to prevent.
3. **Set `ENUMERATE_INSTANCES_URL`** on the supervisor. That is the whole consumer side —
   `_make_enumerator` is written and already logs each call's outcome.

### What actually goes green — measured, and it is not what one would assume

Counts read from the live store, not recalled:

| slot | class | n | at bound 8 | **at bound 10 (corrected 2026-08-30)** |
|---|---|---|---|---|
| `capability_id` | `Capability` | 9 | `too_many` | **a real menu** |
| `project_id` | `Project` | 14 | `too_many` | `too_many` — free text, legitimately |
| `process_id` | `BusinessProcess` | **2** | a real menu | a real menu |
| `tech_id` | `Technology` | **5** | a real menu | a real menu |

> **THE BOUND WAS CORRECTED BY THE PROBE THIS ITEM ASKED FOR.** Ruled at 8 while the ruling's
> own worked example was *"nine capabilities is a menu"* — the number contradicted the case it
> was chosen to justify, and `capability_id` fell to free text because of it. Measured in
> `[[enumerate-probe-2026-08-30]]`, corrected to **10**: still a human-attention bound, now
> consistent with its own reason. `Project` at 14 still answers `too_many`, so the outcome
> stays reachable at the DEFAULT rather than only by lowering the bound inside a test.
>
> **THREE of four spoken-mandatory slots now get a real menu**, not two.

> **STATED BEFORE THE WORK — and half of it was overtaken by the bound correction.** At bound
> 8 the fan-out gave neither live ask case a menu; at the corrected bound of 10, `H06` gets a
> real one and `E05` does not. The paragraph below is preserved as written, because being wrong
> for a measurable reason is the outcome that having written it down early is FOR.
> `H06` (`capability_id`, 9) and `E05` (`project_id`, 14) both exceed the bound and stay free
> text. What changes is that their reason becomes `too_many` **from the provider** instead of
> `no_provider` from an unbuilt hop — which is the entire difference between a decidable boundary
> and a fudge.
>
> **What it does buy: two of the four spoken-mandatory slots get real menus** (`process_id`,
> `tech_id`), and every future slot over a small class gets one for free. Neither has a live
> corpus case today — `H04` and `H05` both resolve cleanly now — so this is capability, not yet
> measured behaviour, and it should be reported that way.

The honest summary of the fan-out's value: **it makes the free-text boundary decidable. It does
not make free text go away.** Anyone expecting menus for the two cases in the record will
otherwise read a correct outcome as a failure.
## OWNERSHIP 2026-08-29 — this item is the FILLER lane's, by the disposition split

Two lanes arrived at the `ask` build at once. Settled: the elicitation lane owns the **disposition**,
this lane owns the **option source it consumes** — see `[[elicitation-ask-disposition]]`'s ownership
section. The filler, resolver and battery are already this lane's surface, and an enumerate provider
is the same territory.

**A second, smaller item travels with it, and it blocks the other lane's acceptance rather than its
build:** `scripts/slot_fill_battery.py` records only `id, cls, conf, expect, got, flags, phrasing`.
The tri-state landed on the `/fill_slots` wire in fix (1) and **does not reach the run artifact**, so
`H06` (elicitation, no candidates) and `E05` (disambiguation, candidate `I1` retained) are both
`got: {}` and **indistinguishable in the file**. The disposition's pre-registered assertion is
*"assert on the reported outcome, not on the absence of a value"* — which no test can do until the
battery records `outcome` and `candidates` per slot. Small, and the acceptance is vacuous without it.

## Open questions this item must answer

**1. Menu length bound.** 9 capabilities is a menu; the triage's **19** resolver candidates is not.
ADR-0033 bounds the *turn* (one) and never bounds the *menu*. This bound is **shared with
disambiguation**, so it is one ruling serving two consumers and belongs wherever it is ruled once.
Related: `[[slot-resolution-entities-in-the-resolver-substrate]]`'s unruled abstention thresholds
(19 candidates *and* exactly 1).

**2. Does enumerate take a filter?** *"which capability"* over 9 is a menu; over 900 it is a search
box, which is free text with extra steps. A `prefix`/`contains` parameter turns `too_many` into a
progressive disclosure — and also turns one turn into two, which ADR-0033 bounds. **Lean: no filter
in v1.** `too_many` → free text, honestly, rather than a search UI smuggled into a bounded turn.

**3. Lifetime — and the precedent is already on file.** Engine P's entities live in an in-memory
`PlanState` a pod restart empties. `[[slot-resolution-entities-in-the-resolver-substrate]]` already
ruled the right shape for `resolve` and it carries over verbatim: **no registry, no declaration
with side effects** (`[[seeder-manufactures-declarations]]`) — the provider answers **live** from
its own state, so an emptied store is correct behaviour rather than staleness. Enumerate inherits
this unchanged; recorded so it is not re-opened.

**4. Whose class vocabulary?** `resolveInstance` returns `class_uri` (an `idp:*` class). A slot
declares `type: "str"` and nothing more (`[[the-filler-has-no-entity-resolution]]` — *"the
declaration is less precise than the requirement"*). **Enumerate needs the slot to name its class**,
which is a declaration-layer change and the same species as the two already filed. Without it there
is nothing to enumerate *over*, and this is the join most likely to be discovered late.

## What this item is NOT

**Not a resolver change.** `resolveInstance` is correct for what it does and its decision table
(`exact | fuzzy | mixed | not_specific | empty`) is the vocabulary the disposition reuses. Nothing
here proposes touching it.

**Not blocked on the elicitation build**, and it does not block it either. The `ask` disposition
ships first on the interim; this converts the interim into a menu.

**Not a fourth registry.** It is one more verb on the existing federated mesh, registered the way
every other provider registers.


---

## BUILT 2026-08-29 — Engine P provider, and two things deliberately NOT done

`POST /enumerate_instances` on Engine P, three outcomes, live from the store, no filter.
Measured at the ruled bound of 8:

| class | members | outcome |
|---|---|---|
| Site / BusinessProcess / Initiative / Technology | 4 / 2 / 3 / 5 | `members` |
| **Capability** | 9 | **`too_many`** |
| **Project** | 14 | **`too_many`** |
| anything else (e.g. a Dataset class) | — | `unsupported` |

**Open question 4 was already closed** by `[[the-filler-has-no-entity-resolution]]`'s fix: a
slot's `referent` carries the class URI, which is exactly this endpoint's input, so a caller
passes the declaration through and needs no vocabulary of its own. Sealed by a test asserting
every class a slot can *declare* is one this engine can *enumerate*.

### The menu bound is ruled at 8, and it disagrees with this item's own example

8 is a **human-attention** bound — what a person can choose from in one turn — replacing a
provisional 15 that had been chosen so no class the seed happens to hold would be truncated,
which is a bound fitted to the data.

> **CONSEQUENCE: `Capability` (9) is now `too_many`.** This item's cardinality section uses
> *"9 capabilities is a menu"* as its example of a menu, so the ruled number and the example
> disagree. `capability_id` and `project_id` are two of the four spoken-mandatory slots, so
> **both of their asks now fall to free text rather than a list.** That may be intended —
> nine items is genuinely a lot to read back in one turn — or it may be an off-by-one against
> the example. Flagged rather than silently reconciled; the number is the ruling.

### NOT DONE (1): the DataHub unboundedness case has no proof, by choice

`too_many` is now exercised against real data (Capability, Project) rather than by lowering
the bound inside a test. What is still unproven is the case this item was written about: a
substrate that is unbounded *in principle* rather than merely larger than eight.

**No synthetic proof was manufactured.** A fabricated 10,000-member class would demonstrate
the code path and nothing about the substrate, and this project has a standing rule against
instruments that agree with whatever they are pointed at.

> **TRIGGER, so the gap is not open-ended: the day an Engine DA (or any DataHub-backed) slot
> declares an instance-typed `referent`.** At that moment a real unbounded class has a real
> slot pointing at it, that provider must answer `too_many` or `unsupported` rather than
> attempting a list, and the free-text boundary gets its first honest test. Until then the
> claim "enumerate over DataHub is unbounded" is a design premise, not a measurement, and it
> is recorded as one.

### NOT DONE (2): the registration is HELD, and must not be hand-seeded

`mesh:enumerateInstances` requires `mesh:InstanceClass` and `mesh:InstanceEnumeration` to
exist as `:OntologyClass` nodes (ADR-0019 Contract D). **Verified against the live graph
before the registration was written: both were MISSING.** They are now declared in
`setup/ontologies/mesh_system.ttl` and reach Neo4j only through an ontology seed.

> **The registration code is committed and NOT DEPLOYED.** Engine P in the sandbox is running
> the previous image, so nothing is attempting this registration and no alarm is firing.
> **Rolling engine-p before the seed would start a permanent Contract D 422 on every boot** —
> a standing red alarm that trains readers to ignore alarms, which is worse than the missing
> capability.
>
> **CONFIRMED 2026-08-29 — the classes are already in the seed manifest.** No
> coordination was needed to add them: `setup/prime_databases.py` LAYER 5 already loads
> `ontologies/mesh_system.ttl`, which is the file they were declared in. The Engine F
> lane is in that same file adding a separate `finance_extension.ttl` entry for its own
> Contract D classes — the manifest is additive, so **one prime run lands both lanes'
> dependencies.** Verified by reading the manifest rather than by asking, which is
> cheaper and does not interrupt a working lane.
>
> **It rides the next coordinated prime window**, not a hand-run Cypher
> (`[[bootstrap-state-debt]]`). Verification after the seed, by name and parent per the prime
> playbook: the two classes exist as `:OntologyClass`, then engine-p's registration set is
> confirmed to be **sixteen** — fourteen verbs, `resolveInstance`, `enumerateInstances` — and
> not fifteen, because a half-registered engine looks healthy from outside and did exactly
> that here this morning.
