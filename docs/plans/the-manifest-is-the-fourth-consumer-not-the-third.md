---
id:         the-manifest-is-the-fourth-consumer-not-the-third
status:     open
owner:      unassigned
blocked-on: the slot_declarations extraction (Lane 1) — this packet is its INPUT, not its blocker
closed-by:
repo:       invincible-agent
ruled-by:   ADR-0046 §9 (the extraction is on slice 1's critical path) — this item SCOPES the manifest against the extraction's real shape, and corrects §9's count
code-site:  agent_fleet/finance_agent/slots.py, agent_fleet/planning_agent/slots.py, agent_fleet/cost_agent/slots.py
summary:    ADR-0046 §9 names the hosted-graph manifest as the THIRD consumer of the slot-declaration derivation and puts the extraction on slice 1's critical path. The third copy already landed — agent_fleet/cost_agent/slots.py, 2026-09-03 — so the manifest is the FOURTH, and §9's measured extraction shape (86 identical lines, one moving target arity_for) predates it. Measured 2026-09-04 across all three - the MECHANISM has forked, not just the vocabulary §9 predicted. slots_for() emits `required` in two engines and `mandatory` in the third; _type_of returns (type, values) in two and a bare str in the third; and the merge surface is now six engine-unique functions, not one. Engine O's _slot_spec reads d.get("required"), so engine-cost's declarations carry no REQUIRED marker to the slot filler — LATENT today because mesh_slots is unprojected, and it fires the moment the projection lands.
---

# The manifest is the fourth consumer, and the mechanism has already forked

**Scoped 2026-09-04** as item 4 of the LangGraph lane — read-only, no cluster, no prime. Its
purpose is that the `slot_declarations` extraction lands against a **real** consumer's needs rather
than an imagined one, per [ADR-0046](../adr/ADR-0046-langgraph-graphs-as-registered-mesh-verbs.md)
§9's own discipline.

## §A — The count is stale, and the correction is not cosmetic

§9 states the manifest is the third consumer and that the third is where duplication *"stops being
a cost and becomes the defect"* (`finance_agent/slots.py`). **The third copy arrived on 2026-09-03
as `agent_fleet/cost_agent/slots.py`.** The manifest is the fourth.

**Engine-cost's author saw it and handled it well** — the module says so by name, keeps itself the
thinnest of the three, and declines to re-implement the referent map or arity *"precisely so the
extraction has less to reconcile rather than more."* That judgment was right. **What follows is not
a criticism of it; it is what the measurement shows happened anyway**, and it is the strongest
available argument that the extraction cannot keep waiting.

## §B — Measured: the MECHANISM forked, which is what §9 said must not happen

§9's measurement (2026-09-01, two copies) found the shared part to be the derivation mechanism and
the divergent part to be each engine's vocabulary, and concluded: *"the extraction takes the
MECHANISM and each engine keeps and passes its own VOCABULARY."* **With the third copy in, that no
longer describes the tree.**

| | finance | planning | cost |
|---|---|---|---|
| `slots_for()` output keys | `name, kind, type, required` | `name, kind, type, required` | `name, type, `**`mandatory`**`, kind` |
| `_type_of()` returns | `(type, enum-values)` | `(type, enum-values)` | **bare `str`** |
| enum values sourced | the parameter's own `Literal` | the parameter's own `Literal` | a hand-mapped `_ENUM_VALUES` table |
| `_is_union` helper | yes | yes | **absent** |

**The required/mandatory split is the sharpest of these** and it is one word. Two engines emit
`required`; the third emits `mandatory`. Engine-cost's own docstring promises the opposite outcome
— *"so a consumer reading declarations from any engine sees one vocabulary rather than three that
agree."*

**The enum-value row is subtler and worth stating precisely rather than as "hand-kept".** Cost's
values ARE derived (`typing.get_args(CostCategory)`); what is hand-kept is the *slot-name → type*
mapping that decides which parameters get a `values` key at all. So a new `Literal` parameter in
finance or planning ships its vocabulary automatically, and in cost it ships silently without one
until someone adds a row.

## §C — The consequence, and it is LATENT rather than live

`agent_fleet/ontology_service/main.py:2673` — Engine O's `_slot_spec`, which renders the prompt the
slot filler works from — reads:

```python
if d.get("required"):
    bits.append("REQUIRED")
```

Engine-cost never emits `required`. **Every engine-cost slot therefore reaches the filler with no
REQUIRED marker**, including `rate_vintage` — the slot its own module names as *the engine's
designed refusal*, with the reason spelled out: *"a refusal the router cannot see is a refusal that
never fires: the question routes, the verb raises, and a caller gets a Python error where they
should have got a menu of vintages."*

**IT IS NOT FIRING TODAY, and the reason must be stated with it.** `mesh_slots` is not projected
into the graph yet — blocked on doc-tools' `aitool_linker` allowlist — so
`decode_declarations(cv.get("slots"))` returns `[]` for **every** engine and every spoken slot is
refused (`src/iagent_pure/slot_acceptance.py:24`, `dynamic_supervisor.py:785`). The carry lands
dark by design, in the order *declare → project → honour*.

**So this is a defect with a scheduled start time.** When the projection lands, finance and planning
light up correctly and engine-cost lights up with every slot optional — and it will not go red
anywhere, because a missing `REQUIRED` line in a prompt has no failure signature. The projection is
the event several lanes are waiting for, which makes this the wrong thing to discover on that day.

**Cheapest correct fix, and it belongs to engine-cost, not here:** emit `required` (keeping
`mandatory` as well if `mandatory_slots()` or the cost seals read it) so the key matches the two
engines that predate it and the consumer that reads it. Note that
`tests/cost/test_engine_cost_contracts.py` asserts on `slots_for` output, so the seal moves with it.

## §D — What the MANIFEST needs from the extraction

ADR-0046 §1's manifest table, mapped onto what exists today. **The point of this section is that no
single engine's copy supplies the manifest's needs** — the manifest is the first consumer that
requires the union, which is a stronger argument for extraction than "three copies is too many".

| manifest row (§1) | supplied today by | where it lives |
|---|---|---|
| slots: name, type, mandatory, defaults | `slots_for()` | all three — **but on two different key names** |
| enum vocabulary for a slot | `slots_for()` → `values` | derived from the `Literal` in F and P; via a hand-mapped table in C |
| slot KIND (4-kind vocabulary) | `SLOT_KINDS`, `HANDLE_SLOTS`, `CEREMONY_VERBS` | all three; **`SLOT_KINDS` is identical in all three and is the one thing safe to hoist verbatim** |
| arity (`single` vs set-shaped) | `arity_for()` | **planning only** |
| refusal contract | `missing_mandatory()` + `refusal_for()` | **finance only** |
| the whole-engine view a manifest renders from | `all_declarations()` | **cost only** |
| live vocabulary injection at render time | `with_live_vocabularies()` | **finance only** |
| subject / output `owl:Class` | — | **not in any `slots.py`**; registration-side, per engine's `CATALOGUE` |
| identity requirements | — | **not in any `slots.py`**; ADR-0046 §1 declares it and nothing derives it yet |

**Three consequences for the extraction, stated as requirements rather than preferences:**

1. **The merge surface is six engine-unique functions, not §9's one.** §9 named `arity_for()` as
   *"one moving target… named here so it does not become a three-way merge."* The real list is
   `arity_for` (P), `missing_mandatory` + `refusal_for` + `with_live_vocabularies` (F),
   `all_declarations` + `mandatory_slots` (C). Every one of them is a manifest row above, so none
   can be dropped as incidental — **the manifest is what proves they are all mechanism.**
2. **Settle the output key FIRST, before the extraction, not during it.** It is the cheapest
   possible fix now and the most expensive after a shared util exists with a compatibility shim in
   it. The consumer (`_slot_spec`) has already voted: `required`.
3. **Two manifest rows have no derivation anywhere** — subject/output URIs and identity
   requirements. The extraction should not invent them; the manifest declares them by hand, and
   this packet records that as a deliberate boundary rather than a gap to be discovered in slice 1.

## §E — What this packet does NOT do

It does not author the manifest schema. ADR-0046 §9 rules that the schema *"should be authored
against a second real consumer rather than designed against an imagined one"*, and slice 2 wakes on
the first real graph a team wants to plug in. **This is the requirements list the extraction should
satisfy, nothing more** — writing the schema now would be the imagined-consumer design that ruling
forbids.

It also makes **no live observation**. Everything above is read from source in this repo on
2026-09-04; nothing was run against the cluster and the sandbox was not touched.

## Related

- [ADR-0046 §9](../adr/ADR-0046-langgraph-graphs-as-registered-mesh-verbs.md) — the critical-path
  ruling and the two-copy measurement this corrects.
- [[slots-are-extracted-then-dropped-at-dispatch]], [[a-missing-mandatory-slot-is-a-400-not-an-ask]]
  — the slot pipeline's other open items.
