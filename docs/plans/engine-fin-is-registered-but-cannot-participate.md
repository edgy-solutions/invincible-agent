---
id:         engine-fin-is-registered-but-cannot-participate
status:     open
owner:      engine-f lane
blocked-on:
repo:       invincible-agent
code-site:  agent_fleet/finance_agent/main.py (ResolveRequest, /resolve_instance), agent_fleet/ontology_service/main.py:~1486 (the fan-out's payload and candidate parser)
summary:    MEASURED on the deployed engine. engine-fin is registered as a mesh:resolveInstance provider — the edge is in the graph, by name — and CANNOT BE CALLED BY THE ROUTER. Two field-name mismatches on the same contract: the fan-out posts {identifier, query} and engine-fin's ResolveRequest requires `text` (every call 422s), and Engine O's parser reads `instance_id` while engine-fin's candidates carry `identity` (so even a successful call yields candidates with empty ids). REGISTERED IS NOT PARTICIPATING, and the registration is what everyone checks. The name-reuse ambiguity the lane described is real and reachable via engine-fin's own shape: "Integration and Test" returns three candidates across ControlAccount, FundingLine and OBSElement.
---

# engine-fin is registered as a resolver and cannot be called by one

## Measured, on the deployed engine

```
POST /resolve_instance {"identifier": "Integration and Test", "query": "x"}   -> 422
POST /resolve_instance {"text": "Integration and Test"}                       -> 200
```

The first is **the exact payload Engine O's fan-out sends** (`ontology_service/main.py`,
`json={"identifier": identifier, "query": query}`). The second is engine-fin's own model:

```python
class ResolveRequest(BaseModel):
    text: str
    class_uri: Optional[str] = None
```

And the response disagrees too. Engine O parses candidates with `c.get("instance_id")`;
engine-fin emits `identity`:

```
candidate keys: ['identity', 'label', 'class_uri', 'score']
```

So **both directions are broken independently.** Fixing only the request field would produce
candidates whose `instance_id` is `""` for every row — resolution reporting success with no
usable id, which is worse than the 422 because it is silent.

## Why nothing caught it

The graph says everything is fine. engine-fin's registration set reads **8 by name**, non-null,
including `mesh:resolveInstance`. The edge exists, the endpoint URL is right, the engine is
healthy, and `/verbs` lists six fin verbs that all answer.

**Registered is not participating**, and registration is what gets checked. Engine O's fan-out
catches provider exceptions and records `status="error"` — by design, so one bad provider
cannot take down resolution — so this fails *quietly* at exactly the layer built to tolerate
it. The same shape as `engine_p_planning_resolve_instance` minting under the deployment name
this morning: the registration succeeded and the participation did not, and only calling it
the way the caller calls it revealed the difference.

> A provider is not tested by its registration. It is tested by the payload its consumer
> actually sends.

## The ambiguity the lane described is real, and reachable

Through engine-fin's own shape:

```
"Integration and Test" -> 3 candidates
   3.1        ControlAccount   "Integration and Test"
   FL-RDTE    FundingLine      "Research, Development, Test and Evaluation"
   OBS-TEST   OBSElement       "Test and Evaluation Directorate"
```

Three classes, one phrase — which is the `mixed` outcome the decision table exists for, and
the case ADR-0033's fourth consumer was scoped around. **It is unreachable through the mesh
until the contract mismatch is fixed**, so the disambiguation work is blocked on this, not on
the disposition.

## The fix is the engine-f lane's

Two renames on engine-fin's side, or an adapter — but **the direction matters and is not
obvious**, so it is worth stating rather than leaving to whoever picks it up:

* `mesh:resolveInstance`'s contract is set by its **four existing providers** and by Engine
  O's parser. engine-fin is the newcomer, so **engine-fin changes**: accept `identifier` (it
  may keep `text` as an alias) and emit `instance_id`.
* Changing Engine O's parser instead would break the four providers that are correct today,
  which is the "fix the majority to match the exception" move this codebase has a rule about.

**Not fixed here.** `agent_fleet/finance_agent/` is the engine-f lane's, and the night sweep
is measurement-only. `enumerate_instances` on engine-fin should be checked for the same class
of mismatch at the same time — it was not probed, and it has a contract too.
