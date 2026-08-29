---
id:         enumerate-is-not-resolve
status:     open
owner:      agent
blocked-on:
repo:       invincible-agent
ruled-by:   ADR-0033 Amendment 2026-08-28 (#2's fourth option source) — this item is the SCOPING of the capability that clause assumes
code-site:  agent_fleet/datahub_wrapper/main.py (the mesh:resolveInstance registration, as the shape to copy), agent_fleet/ontology_service/instance_resolution.py, agent_fleet/utils/mesh_registration.py
summary:    THE MESH CAN RESOLVE AND CANNOT ENUMERATE, and ADR-0033's fourth option source needs the second. `ResolveInstanceRequest` requires `identifier: str` — it SCORES candidates against a string the user said. A slot the phrase never filled has no such string, so registering another resolveInstance provider unblocks name→id and produces NO MENU. The two are different verbs: resolve is `identifier → scored candidates`, enumerate is `class → the members`. CONSEQUENCE THAT ORDERS THE WORK: all four spoken-mandatory slots in the system are instance-kind (capability_id, project_id, process_id, tech_id) — not one enum, not one period — so the ask TRIGGER is free and every menu it could build is blocked. The ask ships before its options can. THE DESIGN QUESTION THIS ITEM OWNS IS CARDINALITY, not plumbing: enumerate over Engine P is 4 sites and 9 capabilities; enumerate over DataHub is unbounded. A provider must be able to answer "not enumerable" — and THAT is what makes ADR-0033's free-text boundary principled rather than a fudge, because free text becomes permitted where a provider REPORTS unboundedness, never where nobody built the capability.
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

| substrate | enumerate `capability_id` | enumerate a DataHub dataset class |
|---|---|---|
| Engine P `PlanState` | 9 | — |
| Engine P projects / processes / tech / sites | 3 / 2 / 5 / 4 | — |
| DataHub | — | **unbounded** |

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
