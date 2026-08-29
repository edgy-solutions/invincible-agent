---
id:         the-filler-has-no-entity-resolution
status:     open
owner:
blocked-on:
repo:       invincible-agent
code-site:  agent_fleet/ontology_service/main.py (/fill_slots), src/iagent/defs/dynamic_supervisor.py (execute_subtask)
summary:    MEASURED. Six spoken slots are OPAQUE IDS (site_id, capability_id, project_id, tech_id, process_id, scope_initiative_id) and the filler has no entity resolution, so it confidently emits the spoken NAME. "how loaded is the Aurora site" -> {"site_id": "Aurora"} at confidence 0.92 -> 422 unknown site 'Aurora'. That is a WRONG fill, not a miss: an honest refusal to a perfectly answerable question. The system ALREADY has the component for this — /resolve and entity_refs, ADR-0031's instance-resolution ladder — so the filler is doing a job another part owns. Also the first evidence on the threshold question, and it points at the harder branch: the wrong fill scored 0.92 where the correct one scored 0.98. Suggestive, n=3, and pre-registers a hypothesis the corpus will settle.
---

# The filler has no entity resolution, and names are not ids

## Measured

Live, against the deployed filler, with `plan_site_load`'s real declarations:

```
how loaded is the Aurora site        -> {"site_id": "Aurora"}       conf=0.92
how loaded is site S1                -> {"site_id": "S1"}           conf=0.98
which sites are overloaded in FY26-Q4 -> {"window": ["FY26-Q4"]}    conf=0.96
```

And the consequence, against the real engine:

```
{"site_id": "Aurora"}  -> 422 {"not_in_model": "unknown site 'Aurora'"}
{"site_id": "S1"}      -> 200
```

**"Aurora" is a real site.** `S1` is named *"Site A — Aurora"*. The question was answerable,
the parameter was spoken, and the answer is a refusal.

## Why this is a WRONG fill and not a miss

The distinction matters because the two failure modes are treated differently everywhere
else in this arc. A miss degrades to a default and is recoverable. This one **produces a
value the verb cannot use**, at high confidence, and the user sees a 422 naming their own
words back at them. It is the confidently-wrong mode with a loud failure instead of a silent
one — which is better, but only by accident of the engine happening to validate ids.

`plan_maturity_grid.as_of` has no such validation: a wrong-shaped value there returns **200
with an unfiltered superset**, which is the silent version of the same defect.

## Six slots are in this class

| slot | verb(s) | what the model is told |
|---|---|---|
| `site_id` | `planSiteLoad`, `planSchedule` | `type: str` |
| `capability_id` | `planCapabilityPath` | `type: str`, REQUIRED |
| `project_id` | `planDependencyNeighborhood` | `type: str`, REQUIRED |
| `process_id` | `planProcessEvolution` | `type: str`, REQUIRED |
| `tech_id` | `planTechFootprint` | `type: str`, REQUIRED |
| `scope_initiative_id` | `planCostCurve`, `planSchedule` | `type: str` |

**The declaration says `str` and nothing more.** It does not say "an opaque identifier", it
does not carry the vocabulary, and there are only 4 sites, 9 capabilities, 3 initiatives, 2
processes and 5 technologies — small, closed, enumerable sets. The model is being asked to
produce a value it has no way to know.

This is the same species as `direction: str` over a closed vocabulary, one step further out:
**the declaration is less precise than the requirement**, and the imprecision runs toward
permissiveness — the model is invited to supply something it cannot get right.

## The system already owns this problem elsewhere

`/resolve`, `entity_refs`, and ADR-0031's instance-resolution ladder exist precisely to turn
"the Aurora site" into a URN. The supervisor already carries `entity_refs` — *"untyped
VALUES, which is why the supervisor can hand them to /resolve but cannot call a verb with
them"*, per the carry's own comment.

So the filler is duplicating a component that exists and is better at this. **The likely
correct architecture is that id-typed slots are not the model's to fill at all**: the filler
handles spoken *parameters* (enums, periods, flags) and the resolver handles *referents*,
with the supervisor joining them. That is a design decision, not a patch.

Two cheaper interim options, both worth weighing against it rather than instead of it:

1. **Declare the vocabulary.** These sets are small and closed. `slots_for` already emits
   `values` for enums; emitting the id↔name pairs for a bounded reference set would let the
   model pick `S1` for "Aurora" the same way it picks `initiative` for "by initiative". Costs
   prompt size and goes stale unless derived at registration.
2. **Refuse rather than guess.** If a slot is id-typed and the offered value is not a known
   id, refuse it at `/fill_slots` — turning a 422 from the engine into a miss, which the
   `ask` path can then handle. Cheapest, and it converts the WRONG class into the
   recoverable one.

## ✅ CLOSED BY FIX (1), run 5 — and "fix (3)" HANDS OFF

**The acceptance item below is met.** Run 5: **WRONG 5 → 0**, the tri-state is live, and `E05` is
refused with its outcome (`wrong_class`) and its candidate **retained rather than passed through** —
which is the contract, built as specified. The arity collapse observed in run 3 did not survive into
the shipped fix.

> **"Fix (3)" — the ask disposition — transfers to the elicitation lane** with its current state.
> Two lanes were pointed at one build; the split is recorded in
> `[[elicitation-ask-disposition]]`'s ownership section. This lane keeps the filler, the resolver
> and the harness, and picks up `[[enumerate-is-not-resolve]]` — the option source the disposition
> will consume — plus one small prerequisite: **the battery must record `outcome` and `candidates`
> per slot.** Without it `H06` and `E05` are both `got: {}` in the run file and the disposition's
> pre-registered assertion cannot be checked by any test.

## ⛔ ACCEPTANCE ITEM ADDED 2026-08-29 — RESOLUTION MUST BE THREE-VALUED

Added by the elicitation lane (`[[elicitation-ask-disposition]]`) as an **acceptance item, not a
suggestion**, because the natural implementation of this fix — *resolve, and fall back to the raw
string when resolution fails* — is precisely the pass-through that recreates the defect one layer
down, where nothing can see it.

> **The join must report `resolved` / `unresolved` / `not-attempted`. Never pass-through-on-failure.**

**Why it is an acceptance item.** A silent pass-through is **indistinguishable at the disposition
point from a successful fill.** `execute_subtask` sees a slot with a value in it and dispatches;
the engine 422s. That is today's behaviour with an extra hop, and the `ask` disposition — whose
trigger is a *spoken-mandatory slot absent after filling* — **cannot fire on it**, because a
presence test cannot see an unresolvable value. Measured on the corpus: `E05` and `H04` both have
their mandatory slot **filled**, with a name, and both route straight to a 422 under a presence
trigger.

**Reuse the vocabulary that exists; do not mint a second one.** `instance_match` in
`agent_fleet/ontology_service/instance_resolution.py` is already
`exact | fuzzy | mixed | not_specific | empty`, and its authors already fought this exact fight —
`empty` was split out of `not_specific` so the gate's actions could not hide inside a not-found.
A second outcome vocabulary beside it is the two-registries shape.

### ⚠ AND THIS IS WHY OPTION 2 ABOVE IS NOT SUFFICIENT ON ITS OWN — NOW OBSERVED, NOT PREDICTED

> **Confirmed by `622f3c8` (run 3), which landed while this item was being written.** The coercion
> fix moved `H04` and `C06` from **WRONG → MISSED** — the filler stopped emitting the spoken name
> and now emits nothing. That is option 2's behaviour arriving as a side effect, and it produced
> exactly the loss described below: `H04` is now an *elicitation* (no menu) where it was an
> answerable *disambiguation* (a name was spoken, candidates exist).
>
> **`E05` did not move** — it still emits `project_id: "ERP Modernization project"` (run 2:
> `"ERP Modernization"`). So the two halves of one shape now disagree: **`H04` drops the name,
> `E05` passes it through, and neither reports that resolution failed.** No prompt rule can make
> this consistent, because whether a string resolves is not a fact the model has.


Interim option 2 — *"refuse it at `/fill_slots` … turning a 422 from the engine into a miss, which
the `ask` path can then handle"* — is **the right instinct and the wrong arity.** It collapses
*unresolvable* into *absent*, and those two take **different option sources**:

| what happened | shape | menu comes from | reachable today? |
|---|---|---|---|
| slot **absent** — the phrase never carried it | elicitation | enumeration from the substrate | **no** — no enumerate capability exists (`[[enumerate-is-not-resolve]]`) |
| slot **unresolvable** — a name WAS spoken | disambiguation | `resolveInstance` candidates for that name | **yes** — the mechanism is built and federated |

So collapsing them **throws away a menu that already exists.** Under option 2 as written, `E05`
("the ERP Modernization project") and `H04` ("Order to Cash") stop being answerable-by-asking and
become blocked on the enumerate capability alongside `H06` — a self-inflicted dependency. Keeping
the distinction lets those two ship with the **original** ADR-0033 #2 option source and no new
substrate at all.

**Green when:** a fill on an id-typed slot whose value does not resolve returns the slot marked
with its `instance_match` outcome **and the candidate list**, rather than the raw string and
rather than nothing. Assert on the reported outcome, never on the absence of a value — the
neighbour-assertion trap, and here the neighbour is the very thing that cannot distinguish the
two cases.

## The threshold question, first evidence — and it points the harder way

The wrong fill scored **0.92**; the correct one **0.98**. The `project_id` omission scored
**0.0**.

If that pattern holds, confidence separates *misses* well and *wrong fills* badly — which is
the branch that matters, because a threshold that catches only misses catches only the
recoverable mode. **Stated as a hypothesis, not a result: n=3.** It is exactly what the
corpus run will settle, and it is why the run must slice confidence by outcome class rather
than reporting one mean.

## What this changes about the corpus

An implied-parameter case on an id-typed slot ("the Aurora site", "ERP Modernization")
currently measures **this gap**, not the filler's phrasing comprehension. That may be exactly
what an author wants — it is a real user phrasing and a real failure — but the expectation
should be written knowing it, and such cases should be marked so the report can separate
"could not parse the phrasing" from "parsed it and had no way to resolve the referent".
