---
id:         engine-cost-answers-as-the-caller-not-the-owner
status:     open
owner:      agent (lane 1) — MECHANISM MEASURED, FIX NOT MADE (two rulings wanted)
blocked-on: a ruling on the zero-verb classes (§4) — engine-cost lane owns the disposition
repo:       invincible-agent
ruled-by:   ADR-0009 Step F'.3/F'.6 (the persona split); ADR-0033 (route | ask | abstain)
code-site:  agent_fleet/cost_agent/main.py (no boot guard), agent_fleet/finance_agent/main.py:256 (the guard it lacks), src/iagent/defs/dynamic_supervisor.py:1880 (acting_persona), tests/routing/test_response_shapes_are_not_groundable.py (the seal that was blind)
summary:    DATA_ENGINEER IS A SYMPTOM, NOT A SELECTION, and nothing picks among alice's eleven cells. `acting_persona` is the CALLER's JWT persona BY DESIGN (dynamic_supervisor.py:1880, "Distinct from owner_persona (the answerer-side)"), and `answerer_persona` collapses to the caller only on the GENERALIST payload, whose own comment says why. So DATA_ENGINEER on a catalog answer is alice's own persona printed on an ENGINE A answer — the real event is that routing fell through. MEASURED CAUSE: the question grounds to `cost#CostCategory` at 0.96, and that class has ZERO VERBS. Two of the five groundable cost classes are unserved (CostCategory, Supplier); the other three route correctly and the registered synonyms reach their verbs at 0.92-0.99. MY OWN PRE-REGISTERED MECHANISM WAS REFUTED: I predicted compatible_count==1 on ProductionProgram would force UNKNOWN, and that path routes fine. ENGINE-FIN FAILS AT BOOT ON EXACTLY THIS CONDITION (_dead_end_classes / _NO_VERB_BY_DESIGN, main.py:256) AND ENGINE-COST HAS NO SUCH GUARD — it would have named CostCategory and Supplier before the engine ever served a request. Separately and mine: the seal that should have covered cost's outputs was BLIND to the lookup-table registration form and harvested zero cost URIs while passing; fixed, 16 -> 42 outputs.
---

# Engine-cost answers as the caller because it answered as the generalist

## What the dispatch believed, and why it is not that

> *"Alice holds eleven cells and something picks the wrong one."*

**Nothing selects a persona from the eleven.** Two personas exist on this path and both are
assigned unconditionally, by design, with the reasons written at the assignment:

| field | source | code |
|---|---|---|
| `acting_persona` | the CALLER's JWT persona | `:1880` — *"Distinct from owner_persona (the answerer-side)"* |
| `answerer_persona` | the matched predicate's `owner_persona` … | docstring at `:1812` |
| `answerer_persona` | …**except on the generalist payload**, where it collapses to the caller | `:1291` — *"Engine A is the generalist so the answerer persona collapses to whoever asked (no specialist owner_persona to inherit from)"* |

So `DATA_ENGINEER` is **alice's own persona on an Engine A answer**. The report that it came
*"from the catalog"* corroborates it: `search_datahub` is Engine A's.

**Reading the persona as a selector defect would have sent the fix to the wrong lane
entirely.** There is no eleven-cell selection bug; entitlement passed and grounding was correct
exactly as reported.

## The measured cause: a groundable class with no verb

```
POOL (PRODUCTION_COST, 5 classes)
  ProductionLot      4 verbs
  ProductionProgram  1 verb
  RateTable          1 verb
  CostCategory       0 verbs   <-- groundable, unserved
  Supplier           0 verbs   <-- groundable, unserved
```

```
is cost per unit falling      -> ProductionProgram  0.99  verbs=1   routes
unit price across lots        -> ProductionProgram  0.92  verbs=1   routes
what did one lot cost         -> ProductionLot      0.97  verbs=4   routes
how did the price build up    -> cost#CostCategory  0.96  verbs=0   -> GENERALIST
```

A question landing on `CostCategory` or `Supplier` cannot route, falls to Engine A, and is
answered from the catalog as the caller. **The classifier is right every time** — the same
sentence Engine F's seam-10 audit reached, about a different engine.

### MY PRE-REGISTERED MECHANISM WAS REFUTED, and recording that is the point of pre-registering

I predicted the fall-through came from `compatible_count == 1` on `ProductionProgram` forcing
`UNKNOWN` for anything that was not a unit-price-trend question. **That path routes fine** —
both of its registered synonyms reach `costUnitPriceTrend` at 0.99 and 0.92. The narrowness is
real and is not what bit. Had I skipped the pre-registration I would have measured the same
numbers and reported the prediction, because the prediction and the truth share a symptom.

## §4 — Engine-fin fails at boot on this; engine-cost has no guard

`agent_fleet/finance_agent/main.py:256` refuses to start when a class it declares is served by
no verb:

> *"engine-fin declares classes no verb serves: … — register a verb on them, or add them to
> `_NO_VERB_BY_DESIGN` with the reason"*

**Engine-cost has no equivalent.** `_dead_end_classes`, `_unroutable_classes` and
`_NO_VERB_BY_DESIGN` do not appear in `cost_agent/main.py`. That guard would have named
`CostCategory` and `Supplier` before the engine ever served a request, and the choice —
register a verb, or declare them drill-down referents with a stated reason — would have been
made deliberately at build time rather than discovered as a wrong persona on a card.

**The disposition is the engine-cost lane's**, and it is the same fork engine-fin already
faced: are these drill-down referents that must stay resolvable (like `fin:WorkPackage`), or a
missing verb? Either is defensible; leaving it undeclared is not.

**The generalisable half is the runbook's:** the boot guard is engine-fin's and lives only
there. It belongs in `docs/runbooks/adding-an-engine.md` as a required step, or shared, because
the second engine to need it did not have it and the third will not either.

## §5 — And the seal that should have covered this was blind

`tests/routing/test_response_shapes_are_not_groundable.py` asserts *every registered
`output_uri` is declared a response shape*. It **harvested zero `cost:` URIs and passed.**

Every measure-based engine registers as `output_uri=measures.OUTPUT_URI[fn_name]` — an
`ast.Subscript` the resolver could not read — and the table's keys are function names, so the
dict scan never matched either. The seal was green over a population excluding **engine-cost,
engine-fin and engine-p**: all three of them.

Two hops were needed, and the second only surfaced because the first half-worked:

1. resolve `mod.TABLE[key]` by parsing the sibling module and taking the whole column;
2. resolve constants **imported** from sibling modules — finance defines `FIN` locally and
   resolved immediately, cost imports `COST` from `.state` and stayed invisible. Same
   construction, different visibility, and a seal that handled only the visible one would have
   stayed green for cost while blind to it.

Harvest: **16 → 42 outputs, 23 → 26 inputs**, with all six cost outputs and three cost inputs
now covered. The seal still passes, which is the correct outcome: cost's outputs **are**
properly declared under `mesh:Response`, and the live pool confirms the filter excludes all six.
The defect was the seal's reach, not the ontology.

This is the enumeration law inside the enforcement mechanism — the same shape Engine F found in
their producer-conformance test the day before, where the archetype population was derived and
the producer population stayed remembered.
