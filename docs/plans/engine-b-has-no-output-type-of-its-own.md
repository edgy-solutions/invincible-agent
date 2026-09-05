---
id:         engine-b-has-no-output-type-of-its-own
status:     open
owner:      unassigned
blocked-on:
closed-by:
repo:       invincible-agent
ruled-by:   ADR-0046 §1 (a registered verb declares both Contract D ends) — this item is why Engine B cannot satisfy it today
code-site:  agent_fleet/langgraph_support/main.py:55 (the import), :262-267 (the return), setup/ontologies/mesh_system.ttl:109-112
summary:    Engine B returns BAML `AgentResponse`, whose graph class `mesh:AgentResponse` is documented as "The final output of a smolagents CodeAgent run" — Engine A's loop, not Engine B's graph. So Engine B has NO OUTPUT TYPE OF ITS OWN, and the Contract D output end it would need in order to register does not describe what it produces. Found 2026-09-01 by the ADR-0046 read. Not urgent while Engine B registers nothing (it calls register_engine_to_mesh zero times), which is exactly why it is worth filing NOW: the borrowed shape is invisible until the moment someone tries to register the engine, and at that moment it looks like a five-minute problem and is a modelling one.
---

# Engine B borrows Engine A's response shape

**Found 2026-09-01**, reading Engine B for [ADR-0046](../adr/ADR-0046-langgraph-graphs-as-registered-mesh-verbs.md).

## What it does

`agent_fleet/langgraph_support/main.py` imports Engine A's BAML types and returns one:

```python
from baml_client.types import AgentResponse, AgentStatus, AgentTask   # main.py:55
...
response = AgentResponse(                                             # main.py:262
    status=AgentStatus.SUCCESS,
    summary=final_state["response_summary"],
    extracted_metrics=final_state.get("extracted_metrics", {}),
)
```

The corresponding graph class says whose output it is:

```turtle
# setup/ontologies/mesh_system.ttl:109-112
mesh:AgentResponse a owl:Class ;
  rdfs:subClassOf mesh:Response ;
  rdfs:label "Agent Response" ;
  rdfs:comment "The final output of a smolagents CodeAgent run." .
```

**Engine B does not run a smolagents CodeAgent.** It runs a two-node LangGraph `StateGraph`. Its
input type is borrowed the same way — `mesh:AgentTask` is *"A multi-step task delegated to a
smolagents CodeAgent loop (Engine A)"* (`mesh_system.ttl:35-38`).

## Why this is a modelling defect and not a naming nit

**A verb's output is a fixed type** ([ADR-0030](../adr/ADR-0030-verb-output-is-a-fixed-type.md)),
and Contract D requires the `output_uri` to resolve to a real `owl:Class` before a registration is
accepted. Engine B's would resolve — to a class that describes a different engine's loop. So the
registration would **succeed while being wrong**, which is worse than failing:

- **Grounding.** A class's `rdfs:comment` is the recall signal. `mesh:AgentResponse`'s comment
  describes a smolagents run, so questions about what Engine B does would ground against prose about
  Engine A — the definition-quality failure mode measured at 12/20 in
  [[response-classes-compete-for-grounding]], arriving from the other direction.
- **Presentation.** Archetype bindings key off `output_uri`. Two engines sharing one output class
  cannot be given different card shapes without a discriminator that does not exist.
- **Provenance.** "Which verb produced this, and what kind of thing is it" collapses to the same
  answer for two unrelated engines.

## Why file it now, while nothing is broken

**Engine B registers nothing** — zero `register_engine_to_mesh` calls — so no bad registration
exists today, and this cannot be observed at runtime. That is precisely the argument for filing it:
the borrowed shape is invisible until someone tries to register the engine, and at that moment it
presents as a five-minute import fix when it is actually *"what does this engine produce, and what
class says so"* — a question that has to be answered before the TTL is written, not after.

ADR-0046 §1 requires a registered graph-verb to declare its own subject and output as real classes.
**This item is the gap between that requirement and Engine B's current state**, and it is on the path
of ADR-0046 §9's slice 1 (re-register Engine B's use case under the contract).

## What the fix is not

**Not "point it at a new class with the same fields."** The shape is a placeholder's shape:
`summary` is an f-string and `extracted_metrics` is two synthetic floats
(`main.py:104-125`). Minting `mesh:SupportResponse` around those fields would ratify a placeholder
into the ontology. The output class is authored **when the graph does something real**, and describes
that — which is the same ordering ADR-0046 §9 gives slice 1.

## Related

- [ADR-0046](../adr/ADR-0046-langgraph-graphs-as-registered-mesh-verbs.md) §1, §9 — the contract this
  gap is measured against, and the slice that closes it.
- [[engine-b-trigger-asset-cannot-succeed]] — the sibling defect from the same read.

---

## 2026-09-05 — the borrowed class is now a LIVE CAUSE, not a naming complaint

This packet has read as a tidiness item: two engines share an output class that describes
neither of them precisely. **It shipped a wrong card.**

Engine A's generalist fallback stamps `output_uri: mesh#AgentResponse` on every answer it gives
(`restate_analyst/main.py:408`, `:3074`). The supervisor's card selector picked *"the first
result carrying an `output_uri`"*, on the stated premise that **only a matched route produces
one**. That premise is false precisely BECAUSE the fallback borrows this class — so a
`no_match` result qualified as card-eligible, and on artifact 12:17 the card rendered a
fabricated entitlement story while the routing record correctly named Engine F.

**The mechanism is the borrowing.** A class that means "the final output of a smolagents run"
is doing double duty as "this result has a renderable output", and a selector cannot tell the
two apart. An engine whose output class described a real answer type would never have been
mistaken for one.

The selector is fixed independently — it now keys on `route_status: matched`, shared with the
routing record through `iagent_pure.primary_selection.pick_primary` — so the card defect does
not wait on this packet. **But the class-borrowing is what made the wrong shortcut look
correct**, and the next selector written against "does it have an output class" will be wrong
the same way.

Recorded here rather than only at the fix, because the fix's commit message will read as being
about a selector, and the reason the selector was wrong lives in this file.
