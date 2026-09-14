---
id:         engine-o-substrate-read-inventory
status:     in-flight
owner:      invincible-agent-28 [5401d7] — ia-eo / lane/eo
blocked-on:
trigger:
closed-by:
repo:       invincible-agent
summary:    The engine-o half of the mesh-client census — every substrate touch engine-o makes, derived from its handles rather than listed, with what each one is TRYING TO DO. The candidate named-operation list MeshGraph / MeshOntology / MeshVectors must cover.
---

# Engine-o's substrate reads — the candidate named operations

**Written for the "the mesh has one client" ADR's interface table, to be CITED rather than
restated.** A message is not citable and survives neither its sender nor its reader; the ADR's
author (docs/ADR lane) and the census owner (`iagent-mesh-sdk-ca`) both need this to still exist
when the addresses have changed.

Scope is `agent_fleet/ontology_service/` at `3247562`. This packet is the ENGINE-O HALF of ca's
fleet census, not the census.

## §0 — HOW THE POPULATION WAS DERIVED, and what the derivation cannot see

Nothing here is hand-listed. A hand-written list of a population is a sample wearing a census's
clothes, so the sites come from the **handles**, in two arms that were reconciled against each
other:

* **Arm 1 — handle references.** An AST walk over `main.py` for every `Name` node in
  `{_NEO4J_DRIVER, _WEAVIATE_CLIENT, _LOCAL_GRAPH, _get_local_graph, _JENA_ENDPOINT,
  _JENA_UPDATE_ENDPOINT}`, each attributed to its INNERMOST enclosing function. 26 sites.
* **Arm 2 — handles passed as parameters.** Arm 1 is blind to a function that receives a driver
  as an argument and never names the module handle. Grep for `.session()` / `session.run(` /
  `.collections.` / `def *(driver` across the package.

**ARM 2 EARNED ITS KEEP, WHICH IS THE POINT OF RUNNING IT.** The two real Cypher executions in
`registry_views.py` (L116–117, L137–138) name no handle — they take `driver` as a parameter — so
arm 1 attributed them to the four thin wrappers in `main.py` (L394–407) instead, and a census
built from arm 1 alone would have recorded the call site and missed the query. The arms
reconcile to the same four logical reads.

**WHAT NEITHER ARM CAN SEE, stated rather than left as coverage:** a substrate reached through a
transport that is not a driver at all. That is not hypothetical here — see F2, which arm 1 found
only because `_JENA_ENDPOINT` happens to be a module-scope name. **Had the Jena URL been read
from the environment at each call site, both arms would have reported a clean absence.**

Every site below is either in the basis (becomes a candidate named operation) or in the
exclusion list WITH A REASON. Nothing is silently dropped.

## §1 — Neo4j: nine reads, and ZERO writes

| site | what it is TRYING TO DO | lands in |
|---|---|---|
| `registry_views.fetch_active_personas` / `fetch_active_domains` (+ the two `*_string` shapers) | read the persona and domain REGISTRY — which personas/domains are active | `MeshGraph.registry(...)` |
| `_discover_enumerate_providers` (L1452) | which engines are registered as `mesh:enumerateInstances` providers, on the resolver TTL | `MeshGraph.providers_for(verb)` |
| `_discover_instance_resolvers` (L1495) | the same read for `mesh:resolveInstance` — endpoint_url, provider, timeout_s, domains | same operation, different verb |
| `_served_class_uris` (L1886) | classes carrying a verb in these domains, plus declared referents — the productive-option gate | `MeshGraph.classes_with_a_verb(domains, include_referents)` |
| `get_physical_assets` (L2440) | `(:OntologyClass {uri})-[:HAS_DATA]->(:DataAsset)` — ontology IRI to physical URNs | `MeshGraph.data_assets_for(iri)` |
| `find_tool` (L2537) | resolve one predicate edge from (subject_uri, verb_label), cheapest by `cost_class` | `MeshGraph.edge(subject, verb)` |
| `find_path` (L2721) | shortest composition start→end respecting allowed cost classes | `MeshGraph.path(start, end, cost_classes)` |
| `operable_subjects` (L3593) | OntologyClass nodes carrying at least one registered verb edge, domain-scoped and can_view-filtered | `MeshGraph.operable_subjects(domain, actor)` |
| `find_compatible_verbs` (L3985) + `_get_subject_ancestor_chain` (L4152) | walk `subClassOf*0..max_hops` and return the predicates that can operate on the subject | `MeshGraph.verbs_for(subject, max_hops)` + `MeshGraph.ancestors(iri, max_hops)` |

**EXCLUDED, with reasons:** `lifespan` (L581) — opens and closes the driver, which is the one
thing an implementation package legitimately does and an interface must never expose;
`health` (L3497) — liveness, and it reports `_JENA_ENDPOINT != ""` rather than reachability,
which is a configuration read wearing a health check's name.

**F1 — ENGINE-O PERFORMS NO NEO4J WRITES AT ALL.** Derived, not assumed: zero matches for
`MERGE (`, `CREATE (`, `DETACH DELETE`, `SET n.`, `CREATE INDEX`, `CREATE CONSTRAINT` anywhere
in the package. **So MeshGraph, as its largest consumer needs it, is a READ interface.** The
graph's writer is `mesh_registrar`. This should decide the ADR's table rather than be discovered
during the build: designing MeshGraph with a write half "for symmetry" would mint a surface with
no caller in the engine that holds the driver, and an unused write path on the one interface
every engine depends on is a wider blast radius bought for nothing.

## §2 — Weaviate: two searches, one existence probe

| site | what it is TRYING TO DO | lands in |
|---|---|---|
| `_weaviate_hybrid_search_sync` (L979) | hybrid search over the `OntologyClass` collection — nominate candidate classes for a phrase | `MeshVectors.nominate(collection, text, domain, scope)` |
| `_predicate_hybrid_search_sync` (L1143) | the same over the predicate collection — nominate candidate verbs | same operation |
| `collections.exists(...)` (L1012, L1164, L2612) | is the collection present at all — the guard that distinguishes "nothing matched" from "nothing to match against" | `MeshVectors.collection_present(name)` |

**The existence probe is not plumbing and should survive into the interface.** It is the local
form of a distinction this repo has paid for repeatedly: an empty result and an absent substrate
are different answers, and a search interface that cannot tell them apart hands its caller a
confident zero. If the interface drops it, every implementation re-invents it privately or stops
making the distinction.

## §3 — Jena: five operations, reached WITHOUT a driver

| site | what it is TRYING TO DO | lands in |
|---|---|---|
| `execute_sparql` (L446) | the internal SELECT executor, read-union scoped `{domain, domain_INSTANCES}` | the executor BEHIND `MeshOntology`, not an operation on it |
| `_run_ask` (L3840) | does this IRI / graph exist — used before a decision-record write (L3770, L3774) | `MeshOntology.ask(...)` |
| `_run_construct_turtle` (L3831) | CONSTRUCT a typed subgraph and return Turtle, types intact | `MeshOntology.construct(...)` |
| `_execute_sparql_update` (L3666) | INSERT DATA into a named graph — the write half (`/write_item_state`, `/write_decision_record`) | `MeshOntology` typed write, or stays engine-o's |
| `_check_jena_populated` (L561) | is the store seeded at all — one row across any graph | startup gate |

**F2 — JENA IS REACHED BY RAW `httpx.post`, NOT BY A DRIVER LIBRARY.** `_JENA_ENDPOINT` is a URL;
the calls are `httpx.AsyncClient(...).post(endpoint, data={"query": ...})` with basic auth
(L505, L3670, L3835, L3844). **A dependency seal that refuses driver PACKAGE NAMES is
structurally blind to this entire substrate** — there is no `rdflib` and no `SPARQLWrapper` on
the path, and `httpx` is not a driver name but here it is the driver.

This is the third arm of the same law, and the three together are the shape the seal has to
cover: ca's *the import name is not the capability*; mine from the `agent_fleet/utils/` hole,
*the pyproject is not the import*; and now **the import is not the connection.** A ban list
operating on names can be defeated by a substrate that needs no name.

**`rdflib` inside engine-o is a LOCAL-FILE parser, not a store client** — `_get_local_graph`
(L429) parses `Maintenance.rdf` and a TTL from disk, and is the fallback when `_JENA_ENDPOINT`
is unset. That corroborates ca's ban-list finding from a second direction: the one engine that
legitimately holds every driver uses rdflib for the same non-driver purpose the three "violating"
engines do.

**F6 — FILED, NOT FIXED, and not mine:** every Jena call passes `verify=False`, and
`_JENA_PASSWORD` defaults to a literal credential in source (L337). Both are pre-existing and
neither blocks this work; recorded here because this packet is the first thing to enumerate that
path, and an observation made during a census that is never written down was not made.

## §4 — F3: THE PATTERN THE ADR PROPOSES ALREADY EXISTS HERE, AT A SMALLER SCALE

`policy_rules_sparql.py`, `state_sparql.py` and `sustainment_instance_provider.py` are **pure
query builders with the executor INJECTED** — the provider's own docstring says so: *"Pure — the
SPARQL executor is INJECTED, so the matching is unit-tested against live-shaped rows without a
Jena."*

So "named operation over an injected executor, testable without the substrate" is not a fleet
convention being imposed on engine-o from outside; **it is engine-o's own local convention,
already carrying its own reason** (a brace bug that cost a build/roll cycle, per
`state_sparql.py`'s header). The ADR should cite these three modules as precedent, and the
migration should start where the shape already holds rather than at the biggest read.

**It also supplies the conformance suite's offline arm for free**: an injected executor is
exactly the seam a fake plugs into.

## §5 — F4: THE FLEET'S PROBLEM IS A MISSING CLIENT, NOT AN OPEN QUERY HOLE

Two derived facts that together narrow the ADR's first increment:

1. **Engine-o's HTTP surface is already 24 named operations** — `grep -c` over
   `@app.(get|post|put|delete)(` in `main.py` — and **not one of them is a raw-query route.**
   There is no `/sparql`, no `/cypher`, and no query string reaching an executor from a request
   body; `/instances_by_property`, the closest case, calls `_build_parts_query(...)`, a builder.
2. **No consumer of `execute_sparql` exists anywhere in `agent_fleet/` outside
   `ontology_service/`.** The passthrough executor is internal.

**So the engines reaching past the SDK to hold their own drivers are not routing around a hole in
engine-o's surface — they are routing around the ABSENCE OF A CLIENT for doors that already
exist.** The first SDK increment is a client over operations engine-o already serves, which is a
much smaller and much better-evidenced piece of work than minting a new capability surface. Where
an engine's direct read has NO corresponding route, that gap is a real SDK backlog item and should
be named as one — but the census will likely produce a shorter list of those than the dispatch
assumed.

## §6 — F5: AN INSTRUMENT CORRECTION, recorded because the shape is a repeat

My first classifier marked a site WRITE when the word `SET ` appeared in its line range. It
flagged `_served_class_uris` — whose docstring reads *"RETURNS AN EMPTY SET ON ANY FAILURE"*. A
check matching a STRING cannot see a BEHAVIOUR, and it flagged the prose EXPLAINING the read as
evidence of a write. Corrected by reading the body; §1's zero-writes claim rests on the absence
of Cypher write keywords, verified separately.

## §7 — WHAT THIS PACKET DOES NOT ESTABLISH

* It is scoped to `agent_fleet/ontology_service/`. It says nothing about the other engines, which
  is ca's census.
* The purposes are read from docstrings and route handlers, corroborated against the query text
  where the query is inline. Where a query lives in a module constant the purpose is the
  docstring's claim, not an independent reading of the Cypher — **a docstring is not evidence**,
  and any operation whose signature turns on a detail of its query text needs that text read
  before it is fixed in the interface.
* No claim is made here about injection-safety of the builder paths. `state_sparql.sparql_lit`
  escapes; whether every builder uses it was not checked, because it is a different question from
  this one and would have arrived as a plausible aside rather than a measured result.
