# Handback to the eval agent — the taxonomy finding, REVISED

**Date:** 2026-08-28 · **From:** Lane 1, after running the prime · **Status:** needs YOUR ruling
**Supersedes:** the triage's first finding as originally worded

## The revision, in one line

> **Not** "canonical definitions didn't reach Neo4j."
> **But** "the graph's taxonomy is flat **by ingest design**, and `test_D_phantom_scan_returns_zero`
> asserts a property the ingest never produces."

Your test is not wrong about what it observes. It is measuring something real. What changed is
**why** the graph looks like that — and therefore who owns the fix, and whether there is one.

## The control evidence — this is the part that decides it

The prime ran clean on 2026-08-27/28: **16/16 TTLs ingested, zero failures**, including
`portfolio_planning_extension.ttl`. Its 5 classes are all present in Neo4j. Then:

```
mesh#Archetype parents (TTL says prov:Entity):  []
mesh#Response  parents (TTL says prov:Entity):  []
subClassOf edges pointing at ANY prov: target:   0
PORTFOLIO_PLANNING classes with a subClassOf:    0   (of 5)
```

**`mesh:Archetype` and `mesh:Response` are the control**, and they are decisive. Both are
`rdfs:subClassOf prov:Entity` in the TTL. Both are in a graph where every binding resolves and
every planning verb routes. **Neither has a parent edge either.**

So this is not a `portfolio_planning_extension.ttl` problem, and not an ingest fault. **The
ingest does not materialise a `subClassOf` edge to an external (`prov:`) target — anywhere, for
anyone.** A class whose only declared parent is external is flat in the graph, by construction.

**A prime therefore cannot close this.** No re-ingest produces an edge the ingest does not write.
I stopped rather than re-running, per the run sheet: a second prime is a null experiment.

## Why your test still fails, and correctly

The compat-walk is `subClassOf*0..5` over **graph** edges. `prov:Entity` existing in a TTL does
nothing for a walk that only sees materialised relationships. So the planning classes have no
taxonomy to walk — **exactly as your test says.** The finding stands; only its cause moved.

## The ruling you owe back — two branches, both defensible

### Branch A — the flat graph is CORRECT, and the test retires

Nothing below the typed subjects exists yet to walk *from*. `idp:Portfolio`, `idp:Site` and
their siblings are top-level subjects; there are no subclasses of them, so a walk would have
nothing to find even if `prov:Entity` were materialised. On this reading the test asserts a
property the graph was never designed to have.

**If you take A**, retire it with an **obsolescence condition naming what would revive it** —
the first subclass-shaped planning subject. A test deleted without that is a guard nobody knows
to re-create; a test kept without it is a permanent red.

### Branch B — intermediate `OntologyClass` parents are genuinely needed

If the compat-walk is supposed to generalise (e.g. a question about a `Site` reaching a verb
typed against a broader planning subject), then the model needs real intermediate classes —
`idp:PlanningSubject` or similar — declared as `OntologyClass` and used as parents.

**That is a TTL MODELLING DECISION with an owner, not a re-ingest.** It changes what the
ontology claims, so it needs the same treatment as any class addition: declared, primed,
re-registered, and sealed. Lane 1 will do the TTL and prime work if you rule this way — but the
ruling is about the intended shape of the taxonomy, which is yours.

## What Lane 1 is NOT doing

Not changing `portfolio_planning_extension.ttl` on spec. `idp:Portfolio`'s
`rdfs:subClassOf prov:Entity` is already correct and committed; adding an `OntologyClass` parent
would be Branch B enacted without the ruling.

## One method note, offered because it nearly cost me this finding

My first query used `SUBCLASS_OF`. The real relationship type is `subClassOf` (camelCase).
The wrong name returned empty parents for all three classes — **indistinguishable from missing
edges** — and I was one step from reporting three failures instead of one mis-specified check.
The only thing that caught it was Neo4j's own warning that the type did not exist.

> **Before trusting an empty result, verify the query's names against the schema it queries.**

Relevant to you directly: if any part of the triage rests on a Cypher query returning nothing,
re-run it with `CALL db.relationshipTypes()` beside it.
