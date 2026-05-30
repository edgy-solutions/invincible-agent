# ADR-0004 — Predicate-graph routing for the agent mesh

**Status:** Accepted
**Date:** 2026-05-29
**Deciders:** Platform team
**Related:**
  - [ADR-0003](ADR-0003-llm-rightsizing.md) (workload-class env vars; same
    "stop using one source-of-truth for multiple things" reasoning, applied
    at the LLM layer instead of the routing layer)

## Attribution

The SPO/predicate-as-tool framing in this ADR was contributed by the team
in conversation on 2026-05-29 while reviewing why the SDK's `ontology_uris`
field on `MeshTool` registrations had no consumer in the mesh. An earlier
attempt to model tools as `(:OntologyClass)-[:SERVED_BY]->(:AITool)` was
caught as a category error — a tool is not a property of a concept; it is
an operator from one concept to another. The reframe and its sharpening
("Symptom → ApplyDiagnostics() → FaultReport") established the model this
ADR codifies. The application of that model to Engine O, the supervisor,
and the registration pipeline is the work the ADR records.

## Context

The mesh currently routes through three orthogonal classification axes that
Engine O classifies with BAML and a TypeBuilder enum:

| Axis | Source | Cardinality |
|---|---|---|
| **Persona** (`MASTER_PERSONAS`) | Python dict at [ontology_service/main.py:106](../../agent_fleet/ontology_service/main.py) | 6 |
| **Domain** (`MASTER_DOMAINS`) | Python dict at [ontology_service/main.py:145](../../agent_fleet/ontology_service/main.py) | 5 |
| **Intent** (`MASTER_INTENTS`) | Python dict at [ontology_service/main.py:133](../../agent_fleet/ontology_service/main.py) | 5 |

Engine O does sophisticated 6×5×5 = 150-cell classification per request.
The supervisor at
[dynamic_supervisor.py:144-152](../../src/iagent/defs/dynamic_supervisor.py)
then collapses the result to **three hardcoded URLs**:

```python
if domain == "DATA_ENGINEERING":              # → DATA_ANALYST_URL
elif domain in ["MAINTENANCE", "MANUFACTURING"]:  # → NEO4J_EXPERT_SVC_URL
else:                                          # → RESTATE_ANALYST_URL
```

The persona Engine O classified gets carried in the payload but does not
affect routing. So the actual fan-out width is the persona count, but the
engine choice is independent of persona — already an internal impedance
mismatch.

In parallel, the SDK (`iagent_mesh.MeshTool`) registers tools to DataHub
with an `ontology_uris: list[str]` field that **nothing in the supervisor
reads**. doc-tools binds *Datasets* to ontology URIs via the
`(:OntologyClass)-[:HAS_DATA]->(:DataAsset)` pattern but has no sibling
pipeline for AITools. So tools register write-only; routing never sees
them.

Three problems compound:

1. **Adding a persona/domain/intent** = source code edit + redeploy of
   Engine O. The dicts are not a registry; they are checked-in constants.

2. **Adding a new tool/engine** has nowhere to land in the routing layer.
   `ontology_uris` writes go to a phantom DataHub endpoint; the supervisor
   is blind to them; the `if domain ==` switch is exhaustive of the
   destinations the system can reach.

3. **The three axes are not actually independent** — they are three
   different projections of one relationship. The 6×5×5 grid inflates the
   schema beyond what the world contains:

   - **Persona** is a label on the **tool** (who/what kind of expert
     serves this kind of question).
   - **Domain** is a namespace of concept URIs — a property of the
     **subject/object** of the operation.
   - **Intent** is what the user is asking the system to *do* — the
     **verb** of the operation.

   Persona, domain, and intent live at three different layers of one
   relation: `(subject) --[verb]--> (object)`, plus metadata on the verb.

## Decision

The mesh adopts a **predicate-graph routing model**:

> A tool, agent, or engine **is** a named, typed predicate. The
> registration of a tool is the creation of an `owl:ObjectProperty`
> (in RDF terms) or a typed Neo4j relationship — a named edge between two
> concept classes — that carries the routing metadata as edge properties.

Routing decisions become graph traversals. Persona, domain, and intent
become projections of the predicate graph, not independent classification
axes.

### Canonical shape — RDF

```turtle
@prefix mesh: <urn:iagent:mesh#> .
@prefix mro:  <urn:iagent:ontology:mro#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .

mesh:applyDiagnostics
    a               owl:ObjectProperty ;
    rdfs:label      "applyDiagnostics" ;
    skos:altLabel   "diagnose", "troubleshoot", "find fault in" ;
    rdfs:domain     mro:Symptom ;
    rdfs:range      mro:FaultReport ;
    mesh:endpoint_url      "http://engine-a.mesh.svc:8081/execute" ;
    mesh:openapi_schema    "{...}" ;
    mesh:owner_persona     "MECHANIC" ;
    mesh:cost_class        "fast" ;
    mesh:latency_budget_ms 5000 ;
    mesh:requires_human_approval false ;
    mesh:version           "0.1.0" .
```

### Canonical shape — Neo4j

```cypher
MERGE (s:OntologyClass {uri: "mro:Symptom"})
MERGE (o:OntologyClass {uri: "mro:FaultReport"})
MERGE (s)-[v:applyDiagnostics {
    iri:                     "mesh:applyDiagnostics",
    synonyms:                ["diagnose", "troubleshoot", "find fault in"],
    endpoint_url:            "http://engine-a.mesh.svc:8081/execute",
    openapi_schema:          "{...}",
    owner_persona:           "MECHANIC",
    cost_class:              "fast",
    latency_budget_ms:        5000,
    requires_human_approval:  false,
    version:                 "0.1.0"
}]->(o)
```

The Neo4j relationship **type** is the verb. Its **properties** carry the
runtime metadata. Both subject and object are members of the same
`:OntologyClass` graph that the existing Dataset binding flow uses.

### Routing query (single-step)

Engine O's `/find_tool` becomes:

```cypher
MATCH (s:OntologyClass)-[r]->(o:OntologyClass)
WHERE s.uri = $subject_uri
  AND ( type(r) = $verb_iri OR $verb_label IN r.synonyms )
RETURN r.endpoint_url AS endpoint,
       r.openapi_schema AS schema,
       type(r) AS verb,
       o.uri AS output_uri
ORDER BY CASE r.cost_class WHEN 'fast' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END
LIMIT 1
```

### Composition query (multi-step workflow)

```cypher
MATCH path = (start:OntologyClass {uri: $start_uri})-[*1..4]->(end:OntologyClass {uri: $end_uri})
WHERE all(rel IN relationships(path) WHERE rel.cost_class IN ['fast','medium'])
  AND all(rel IN relationships(path) WHERE rel.requires_human_approval = false)
RETURN [rel IN relationships(path) | { verb: type(rel), endpoint: rel.endpoint_url }]
       AS steps,
       length(path) AS hops,
       reduce(t = 0, rel IN relationships(path) | t + rel.latency_budget_ms) AS total_budget
ORDER BY hops ASC, total_budget ASC
LIMIT 1
```

The supervisor walks the returned `steps` list, threading the output of
step N as input to step N+1. **No `if domain ==` switch anywhere.** A new
tool registered tomorrow becomes part of the path search the next request.

### The three "dimensions" as projections

Personas, domains, and intents stop being parallel sources of truth.
They are derived queries over the predicate graph:

| Old concept | New form |
|---|---|
| `MASTER_PERSONAS` list | `MATCH ()-[r]->() RETURN DISTINCT r.owner_persona` |
| Persona UI metadata (icon, color, label) | A small `mesh:Persona` entity type maintained alongside the verb registry. **Not in source code.** |
| `MASTER_DOMAINS` list | `MATCH (c:OntologyClass) WITH split(c.uri, ":")[0] AS ns RETURN DISTINCT ns` |
| `MASTER_INTENTS` list | The verb hierarchy itself: `MATCH (v:VerbRegistration) RETURN v.iri, v.parent_iri` — sub-property chains become intent categories |
| `DecomposeQuery` → tasks per persona | Path-finding produces edge sequences; persona is read off each edge as a side-effect, used for UI "Agents assembling" broadcasts |
| Supervisor `if domain ==` switch | **Deleted.** Replaced by `/find_tool` or `/find_path` |

The 6×5×5 grid still exists at *runtime* — Engine O can still build a
BAML TypeBuilder with the same dimensions — but its contents are
**derived** from the verb graph instead of from source-code dicts.
Adding a new persona is the side effect of registering a tool that
declares `owner_persona: "NEW_PERSONA"`.

## Concrete end-to-end example

A maintenance query, processed through the new model:

1. User asks: *"Why is the rotor making a whining noise after 8000 flight hours?"*

2. Engine O `/route_and_plan` calls BAML with a TypeBuilder enum sourced
   from the verb graph:
   - candidate verbs (from edge types): `applyDiagnostics`,
     `searchManualText`, `lookupPart`, `recommendReplacement`, …
   - candidate subject concepts (from `OntologyClass` nodes):
     `mro:Symptom`, `mro:RotorAssembly`, `mro:FlightHours`, …

3. BAML returns: `{ verb: "applyDiagnostics", subject_uri: "mro:Symptom" }`

4. Engine O `/find_path(start="mro:Symptom", end="mro:FaultReport")` runs
   the composition query. Returns:
   ```
   [ { verb: "applyDiagnostics",
       endpoint: "http://engine-a.mesh.svc:8081/execute" } ]
   ```

5. Supervisor walks the one-step list, POSTs the user's request to the
   endpoint, returns the FaultReport.

For a two-step workflow (*"diagnose, then write up the maintenance log"*),
the same query returns:

```
[ { verb: "applyDiagnostics",   endpoint: "http://engine-a..." },
  { verb: "formatTechnicalNote", endpoint: "http://engine-f..." } ]
```

Supervisor walks both, threading the FaultReport from step 1 as input to
step 2.

## Build sequence

Six steps. Each ships independently and works on its own.

### Step A — extend the SDK registration shape

`iagent_mesh.MeshTool` gains four constructor arguments:

```python
MeshTool(
    name="anomaly_detector",
    description="...",
    verb="detectAnomalies",                    # mesh:detectAnomalies
    verb_synonyms=["find outliers", "flag anomalies"],
    input_uri="mro:DatasetSnapshot",           # rdfs:domain
    output_uri="mro:AnomalyReport",            # rdfs:range
    owner_persona="DATA_STEWARD",              # optional, for UI roster
    cost_class="fast",                         # optional
)
```

Keep `ontology_uris` accepted-but-deprecated for one minor version.
The lifespan registration writes these fields as DataHub `aiTool`
custom properties via `MetadataChangeProposalWrapper`. **Nothing reads
the new fields yet** — Step A is just plumbing.

### Step B — doc-tools AITool binding plane

Clone the existing `(:OntologyClass)-[:HAS_DATA]->(:DataAsset)` pipeline
in doc-tools as a sibling for AITools:

- `ingest_global_aitool_links` — polls DataHub for `entityType=AITool`
  with `verb` / `input_uri` / `output_uri` custom properties
- `sync_aitool_predicate_to_neo4j` — emits the
  `(:OntologyClass)-[v:{verb} {endpoint_url, owner_persona, ...}]->(:OntologyClass)`
  edge

No HITL for code-controlled tools (unlike legacy DB tables which need
human classification). Auto-approve. Dagster sensor fires within ~30s
of registration.

### Step C — Engine O `/find_tool` (and `/find_path`)

Two new endpoints, both pure Cypher traversals:

```
POST /find_tool   { subject_uri, verb_label }      → { endpoint, schema, verb }
POST /find_path   { start_uri, end_uri, max_hops } → { steps: [...] }
```

**No BAML, no Weaviate, no LLM in either endpoint.** They are
deterministic graph queries. Engine O's existing `/resolve` and
`/route_and_plan` stay as the NLP-side of the system and *call* these
new endpoints.

### Step D — supervisor migration

Replace
[dynamic_supervisor.py:144-152](../../src/iagent/defs/dynamic_supervisor.py)
with a `/find_path` call + step iterator. Hardcoded engines
(Engine A, E, etc.) self-register as predicates via the same SDK contract
— they become first-class peers to SDK-registered tools. The supervisor
no longer cares whether an endpoint is "a legacy engine" or "a
user-registered tool."

### Step E — derive personas/domains/intents

Replace the `MASTER_*` dicts at
[ontology_service/main.py:106-150](../../agent_fleet/ontology_service/main.py)
with view-functions over Neo4j:

```python
async def get_persona_registry() -> dict[str, PersonaInfo]:
    cypher = """
    MATCH ()-[r]->()
    WITH DISTINCT r.owner_persona AS p
    MATCH (info:Persona {key: p})
    RETURN p AS key, info.label, info.icon, info.color, info.bg, info.llm_prompt
    """
    ...
```

Day-one contents are unchanged — seed Neo4j with the same six personas,
five domains, five intents. But the **source of truth** has moved out of
source code. Future personas/domains/intents arrive through doc-tools'
ontology ingestion or through tool registrations.

### Step F — NLP layer continuation

Engine O's `/route_and_plan` continues to do BAML+TypeBuilder, but the
enums it builds are now sourced from Step E's view-functions. New verbs
registered by tools immediately become routable without code changes.
The NLP layer is otherwise unchanged.

## Consequences

**Wins:**

- **Adding a tool is a Cypher MERGE.** No code change in Engine O or
  the supervisor for a new capability to be reachable.
- **Composition becomes free** — multi-step workflows are graph paths,
  not handwritten Dagster jobs.
- **Personas/domains/intents stop being parallel sources of truth.**
  One registry, three projections.
- **Routing decisions become testable.** Cypher queries over a Neo4j
  fixture, no LLM in the loop. The LLM seam becomes
  `NL → (verb_label, subject_phrase)` only, which is mockable.
- **Policy lives on the edges.** `cost_class`, `latency_budget_ms`,
  `requires_human_approval` are predicate properties — the supervisor
  filters on them as graph queries.
- **The SDK's `ontology_uris` field finally has a consumer** (in its
  new, correctly-typed form: `verb` + `input_uri` + `output_uri`).
- **Stops the doc-tools/SDK impedance mismatch** — both write through
  the same DataHub propose-approve-sync pattern, just to different
  entity types.

**Costs:**

- **Migration cost.** Five steps plus the seed work to populate Neo4j
  with the current persona/domain/intent contents. ~2 sprints of focused
  work, not a weekend.
- **Doc-tools surface area grows.** A new sibling pipeline ~250 LOC.
  Acceptable; the pattern is already proven for Datasets.
- **The hardcoded engines (A, E, etc.) need to register themselves as
  predicates** before the supervisor's `if` switch can be removed. If
  they don't migrate, the switch has to coexist with `/find_path` for
  a deprecation window.
- **Verb namespace governance** becomes a real concern — see open
  question 1 below.

## Alternatives considered

- **Keep the 3D enum model and hardcode dispatch (status quo).** Rejected.
  The hardcoding-and-redeploy cost compounds; the architecture is
  already at its limit (3 hardcoded URLs vs N tools registered to a
  phantom endpoint).

- **`(:OntologyClass)-[:SERVED_BY]->(:AITool)` edge.** Rejected. Category
  error: this models tools as *things possessed by concepts*, like
  datasets. A tool is an *operator*, not a possession. The predicate
  model captures the operator semantics directly.

- **Service-discovery without ontology (Consul, k8s Service annotations,
  etc.).** Rejected. We need *semantic* routing — "what tool can answer
  a question about rotor wear" — not just "where does service X live."
  The ontology binding is the point.

- **Property-only RDF in Jena, no Neo4j.** Rejected for runtime routing
  even though we keep RDF as the canonical declarative form. SPARQL
  property-path queries are powerful but predicates can't easily carry
  the metadata properties (`endpoint_url`, `cost_class`) without RDF-star
  or awkward reification. Neo4j relationships are first-class with
  properties; the runtime mapping is cleaner.

- **Per-engine env-var routing tables** (`ENGINE_A_VERBS=...`,
  `ENGINE_E_VERBS=...`). Rejected. Same anti-pattern as
  [ADR-0001](ADR-0001-mem0-llm-decouple.md) rejected: routing belongs to
  the workload class (verb) and the concept (subject), not to the engine.

- **Stay with persona+domain+intent but make them dynamic.** Rejected
  as half-measure. Solves the redeploy cost but not the 6×5×5 inflation,
  not the missing tool-routing layer, not the persona-vs-domain
  impedance mismatch in the supervisor.

## Open design questions (follow-up ADRs)

These three decisions are deliberately *deferred* from this ADR. Each is
its own decision and warrants its own context section.

1. **ADR-0005 (TBD) — Verb namespace convention.** Are tool-owned verbs
   in `mesh:` (platform-reserved namespace) and domain-owned verbs in
   their domain namespace (`mro:`, `logistics:`)? Or do all verbs live
   in `mesh:` regardless of which domain they operate on? Affects every
   future tool author. Recommendation pending: `mesh:` for the verb
   identity, with domain prefixes on the *subject/object* URIs that
   bracket it.

2. **ADR-0006 (TBD) — Canonical verb registry location.** DataHub is
   the inbox (SDK writes go there via `MetadataChangeProposalWrapper`),
   Neo4j is the consume side (Engine O reads from it). The propose-
   approve-sync pattern matches what doc-tools already does for
   Datasets. But: is DataHub authoritative, or is Neo4j? The HITL
   approval queue exists in DataHub; the runtime queries hit Neo4j.
   We need to pin down which one wins on conflict.

3. **ADR-0007 (TBD) — System-level concepts for compound workflows.**
   Engine F (presentation) takes "raw aggregated data" and produces "UI
   components." Neither side is a real domain concept. We need a small
   set of `mesh:` system concepts (`mesh:RawAggregatedData`,
   `mesh:UIInstruction`, possibly `mesh:UserQuery`, `mesh:RoutingTrace`)
   for these system-level verbs to terminate cleanly. Decide before
   Step B so doc-tools emits consistent edges.

## What this gives us for testing

This is part of why the ADR lands now rather than after the test suite.
With the predicate-graph model:

- **Routing is a Cypher query** → unit-testable with a Neo4j fixture,
  no LLM.
- **Adding a tool is a Cypher MERGE** → tests parametrize over
  *"given these tool edges, given this subject, expected route is X."*
- **The supervisor's path execution is a list-walk over edge
  properties** → deterministic.
- **Engine O's NLP step has a clear seam** —
  `(NL) → (verb_label, subject_phrase)` — that mocks in unit tests and
  exercises live in integration tests.
- **The duplicate-Dagster-runs bug becomes testable** because
  `DagsterRunTracker`'s contract gets pinned down: it dedupes on
  `(verb_iri, subject_instance, user_id, time_window)` — explicitly,
  not on a UUID that the UI may or may not send.

The current 3D-with-LLM-everywhere architecture is hard to test *because*
the routing logic is fused with the LLM call. The predicate-graph
architecture pulls them apart cleanly.

## Indicators for revisiting

- **Some tools turn out not to fit the verb/predicate model.** For
  example, a tool with multiple typed inputs, conditional outputs based
  on internal state, or no clean output concept. We may need to extend
  the model (e.g., n-ary verbs as reified nodes) or accept that a small
  fraction of tools live outside the predicate graph and route via a
  fallback mechanism.
- **Neo4j proves the wrong substrate.** If we end up needing federated
  graph queries across multiple knowledge graphs (e.g., one per
  customer), or full SPARQL/OWL reasoning over the predicate graph at
  runtime, the runtime side may want to move to Jena or a hybrid setup.
  The RDF canonical form means migrations are localized.
- **An LLM matures that can do all routing without a registry.** GPT-6
  or Claude-Opus-Next with massive context could in principle ingest the
  full registry per request and select tools without a Cypher query.
  Latency and cost still favor the registry approach for now, but if
  inference becomes free, this trade flips and the registry becomes
  pure governance metadata rather than the runtime lookup table.
- **DataHub stops being a viable propose-approve-sync inbox.** If the
  organization moves off DataHub or DataHub's custom-property API
  becomes unworkable, we move the propose-approve flow to a small
  dedicated service. The Neo4j runtime side is unaffected.
