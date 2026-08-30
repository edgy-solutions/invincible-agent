---
id:         night-sweep-loose-ends
status:     open
owner:
blocked-on:
repo:       invincible-agent
code-site:  agent_fleet/mesh_registrar/main.py (_build_rel_props_for_saga), the rendersAs registration path
summary:    MEASURED post-prime, and the standing claim needed correcting before it could be reported. "frontend_id = None on all 42 rendersAs edges" is not what the graph says: the property IS NOT ON THE EDGES AT ALL — 0 of 43 carry it, and 0 carry `archetype` either. Absent and null are different facts and only one of them points at the registrar. Also measured: 18 of 43 rendersAs edges render KnowledgeDocument, which is the fallback archetype, so nearly half the presentation surface is registered to the shape that means "nothing more specific matched". And 33 of 43 now carry `slots`, so the mesh_slots projection reached presentations as well as verbs.
---

# The rendersAs loose ends — and the standing claim was stated wrong

## `frontend_id` is ABSENT, not null

The item said *"`frontend_id = None` on all 42 (now 43+) `rendersAs` edges"*. Measured:

```
rendersAs edges                     : 43
edges WITH a frontend_id property   :  0 of 43
edges WITH an archetype property    :  0 of 43
edges WITH a slots property         : 33 of 43
```

**Neither property exists on any edge.** The first query I wrote returned "43 with
`frontend_id` = None" and Neo4j warned `property key does not exist` — the same defect as the
`e.verb` check that returned eight `None`s this morning, walked into again by me, six hours
after I wrote the rule into the playbook. A missing property and a null property read
identically through `r.frontend_id`, and only an existence check separates them.

**The distinction is the whole finding.** `None` would mean the registrar wrote the key and
had nothing to put in it — a value problem, fixable at the caller. **Absent** means the
registration path never emits the key at all, which is a *projection* problem in
`_build_rel_props_for_saga`, the same enumeration that needed a row for `slots`. ADR-0017's
menu-scoping reads `frontend_id` to resolve a caller's own menu; with the key absent, every
caller resolves to the global table.

The archetype is carried as `_output_uri`, not as an `archetype` property — so a reader
looking for the archetype by that name finds nothing and may conclude the edges are unbound.

## 18 of 43 render `KnowledgeDocument`

```
 18  KnowledgeDocument      <- the fallback
  3  ProcessTopology
  3  AssetStateMetric
  3  HazardDeclaration
  3  ChartWidget
  2  IntervalTimeline
  1  WorkflowObservation
  1  InstancesByProperty
```

**Nearly half the presentation surface is registered to the archetype that means "nothing more
specific matched."** That is not necessarily wrong — some outputs genuinely are documents —
but it is the shape the `archetype-chosen-before-data` work was about, and nobody has counted
it before. Worth a deliberate read of whether those eighteen are documents by intent or by
default.

## `slots` reached presentations: 33 of 43

The `mesh_slots` projection went in for verbs, and presentations get it too — 33 of 43 carry
the key. The 10 without are registrations that predate it. Harmless (absent means `[]` means
today's behaviour) and worth knowing, because a consumer that assumes the key is present on
every edge will meet ten that lack it.

## The two stale E/W edges — found, and they are FQDN twins

They are duplicate registrations of the same verb at the same service, differing only by
hostname form:

| verb | endpoints |
|---|---|
| `mesh:queryKnowledgeGraph` | `iagent-engine-e.sandbox.svc.cluster.local:8086/query_graph` **and** `iagent-engine-e:8086/query_graph` |
| `mesh:retrieveKnowledge` | `iagent-engine-w.sandbox.svc.cluster.local:8088/query_knowledge` **and** `iagent-engine-w:8088/query_knowledge` |

Leftovers from before the `svcDomain` templating landed. **Both forms resolve in-cluster**, so
neither edge is dead — which is exactly why they survived. The cost is that the compat walk
sees two records for one verb and the supervisor's `predicate_endpoint_skew` path exists to
arbitrate precisely this; a verb with two endpoints is one re-registration away from the
authority question being decided by ordering.

**A third short-form is registered and was not in the loose-end:** `mesh:resolveInstance` at
`http://iagent-engine-o:8084/resolve_instance` — engine-o self-registers using
`ONTOLOGY_SVC_SELF_URL`, whose default is the bare name, while engine-d, engine-e, engine-fin
and engine-p all register FQDNs. Not a duplicate (engine-o is a distinct provider), but the
same drift, and it will become a twin the day anyone templates that default.

**And one duplicate that is NOT a hostname twin**, surfaced by the same query and worth a
different look: `mesh:proposeDisposition` is registered at two *different* Restate handlers —
`PcnReviewStarter/start_review` and `ReviewStarter/start_review`. Two implementations of one
verb, not two names for one implementation. Unowned by this sweep; recorded because the query
that found the FQDN twins found it too.

## Not chased

Nothing from the loose-ends list remains unreached. What the sweep did NOT do is decide which
of each twin should survive — that is a registration-authority call, and deleting a graph edge
is a mutation the night dispatch excludes.
