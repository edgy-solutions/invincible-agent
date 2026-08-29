---
id:         the-slot-filler-belongs-where-the-verb-is-known
status:     open
owner:
blocked-on: doc-tools projection (mesh_slots -> the graph edge); then a decision on this doc
repo:       invincible-agent
code-site:  agent_fleet/ontology_service/main.py (/route_intent, and the proposed /fill_slots), src/iagent/defs/dynamic_supervisor.py (execute_subtask, beside the carry)
summary:    THE RECORDED RULING CANNOT BE BUILT AS STATED, and this says so rather than quietly redesigning. The ruling was "/route_intent calls BOTH ExtractIntent and RouteIntent in sequence". /route_intent receives ONLY the query — ADR-0009 Step F'.6 removed candidate_verb, and verb resolution now happens in the SUPERVISOR via /search_predicates + /classify_predicate. At /route_intent time there is no verb, so no intent class, so no declarations to fill against or validate with. The ruling's own reasoning survives intact and points one hop later: fill slots WHERE THE VERB IS KNOWN, which is execute_subtask, immediately before the carry. Recommended: a new /fill_slots(query, verb_iri, declarations) endpoint, generic over declarations via TypeBuilder — the pattern this repo already uses for the predicate dynamic enum — so every engine that declares slots gets filling for free rather than planning getting a bespoke path. BAML's existing RouteIntent (18 hand-maintained typed intents, 0 callers) is NOT the vehicle: it re-routes, which would put a second router in disagreement with the graph. Blocked on the projection either way, because a filler with no declarations has nothing to fill.
---

# The slot-filler belongs where the verb is known

## The ruling, and why it does not fit the code

Recorded in `[[slots-are-extracted-then-dropped-at-dispatch]]`:

> `/route_intent` calls **both, in sequence**. `ExtractIntent` decides MODE; `RouteIntent`
> fills TYPED SLOTS **once a verb candidate exists**.

The clause doing the work is the last one, and `/route_intent` does not satisfy it:

```python
@app.post("/route_intent", response_model=RouteIntentResponse)
async def route_intent(request: RouteIntentRequest) -> RouteIntentResponse:
    intent = await b.ExtractIntent(user_query=request.query)
```

It receives **the query and nothing else**. ADR-0009 Step F'.6 deliberately removed
`candidate_verb` — *"Engine O's /search_predicates runs Weaviate hybrid over the raw user
query directly, so an LLM-extracted verb is a lossy intermediate step"* — and verb resolution
moved into the supervisor's `/search_predicates` + `/classify_predicate` pair.

So at `/route_intent` time there is **no verb, no intent class, no declarations**. A
slot-filler there would be filling against every intent at once, which is precisely the
alternative the ruling rejected when it refused to grow `ExtractedIntent`'s fields.

**The ruling's reasoning is right and its address is one hop stale.** "Fill slots once a verb
candidate exists" resolves to `execute_subtask`, immediately before the carry — the same
place `accept_slots` already stands, and the first point in the system where the phrase and
the verb are both in hand.

## Recommended: `/fill_slots`, generic over declarations

A new Engine O endpoint, called by the supervisor between predicate resolution and dispatch:

```
POST /fill_slots
  { "query": "...", "verb_iri": "...", "declarations": [ …the verb's mesh_slots… ] }
  -> { "slots": {"group_by": "initiative"}, "confidence": 0.9, "reasoning": "..." }
```

**Generic over declarations, not per-verb**, built with TypeBuilder — the pattern this repo
already runs in production for the predicate dynamic enum (`contracts.baml:984`: *"builds a
Predicate TypeBuilder dynamic enum from those 10 verb_iris"*). The declarations carry
everything a dynamic class needs: `name`, `type`, `required`, `values`, `default`.

Three properties that matter more than the saved typing:

* **every engine that declares slots gets filling for free.** Planning is the first
  registrant, not the only one. A bespoke planning path would have to be rebuilt for the
  second engine, and the registration mechanism (`mesh_slots`) is already engine-agnostic.
* **the vocabulary offered to the model is the verb's own**, read from its `Literal` — the
  model cannot invent `group_by="by_vibes"` because that value is not in the enum it was
  handed.
* **`handle` and `ceremony` slots are never shown to the model at all.** The guard refuses
  them if they arrive; not offering them means they cannot arrive. Defence in depth, and the
  outer layer stays because a declaration can be wrong (`_type_of` already was).

## Not the vehicle: BAML's existing `RouteIntent`

`planning_qa.baml:286` defines `RouteIntent(question, context) -> ShowCostCurve |
ShowFundingGap | … | NoIntentMatch` — 18 hand-maintained typed intents. **Zero callers**, and
it should stay that way for this purpose:

* **it re-routes.** It picks the intent AND fills the slots, so adopting it puts a second
  router in the pipeline disagreeing with the graph walk that ADR-0009 Step F'.6 deliberately
  made authoritative. That is the "collapse two stages into one call" the ruling refused.
* **it is a fifth registry.** Eighteen classes hand-maintained beside signatures,
  `mesh_slots`, `DERIVED_BINDINGS` and `KNOWN_ARCHETYPES` — and hand-transcription is the
  drift this whole arc has been removing.
* **it is planning-only.** `RouteMoneyIntent` next door is already the narrowed-family
  variant, which is what per-verb classes turn into as they multiply.

It remains useful as a *prompt corpus*: its per-class descriptions are good slot-filling
instructions and should be mined for `/fill_slots`'s prompt rather than deleted unread.

## Sequencing — it is blocked, and blocked on the same thing everything else is

`/fill_slots` needs `declarations`, which reach the supervisor on the predicate, which
requires **doc-tools' allowlist row** (`doc-tools@e6418a2`, corrected at `497f976`). Until
then the supervisor holds `[]`, `accept_slots` fails closed, and a filler would be filling
against nothing.

Building it ahead of the projection would produce code that cannot be tested end to end and
whose green tests would mean nothing — which is the *carried-then-never-filled* near-miss the
finding already recorded once. **Order stays: declare → project → fill → honour.**

The three deterministic joins are done and proven by fixtures (`test_slot_carry.py`); the
model join is the only one left, and it is the only one that needed a model.

## What to decide

1. **`/fill_slots` on Engine O, called by the supervisor** — recommended above.
2. Fill in `execute_subtask` directly via a BAML client in the supervisor — refused: the
   supervisor talks to engines over HTTP and holds no BAML client, and giving it one puts
   prompt maintenance in the orchestrator.
3. Two-pass `/route_intent`, called again after routing with the verb — smallest diff,
   but it makes an endpoint documented as *"stateless and side-effect-free… the gateway can
   call this on every request"* mean two different things depending on when it is called.
