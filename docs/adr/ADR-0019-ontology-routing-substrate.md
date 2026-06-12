# ADR-0019 — The ontology is the routing substrate: coverage, governance, and the (S,P) resolution contract

**Status:** Proposed
**Date:** 2026-06-08
**Deciders:** Platform team
**Related:**
  - [ADR-0004](ADR-0004-predicate-graph-routing.md) — established the
    predicate graph and "a tool *is* a predicate." This ADR states the
    *substrate* frame ADR-0004 implied but never wrote as a decision, and
    adds the coverage/governance layer ADR-0004 assumed would exist.
  - [ADR-0008](ADR-0008-routing-fallback-policy.md) — the Engine A
    generalist fallback. This ADR makes that fallback the *universal*
    convergence point for every low-confidence routing outcome, and fixes
    the current inversion where the least-grounded case takes the most
    dangerous path.
  - [ADR-0009](ADR-0009-sunset-classification-axes.md) — retired
    persona/domain/intent as routing axes. This ADR reinforces "resolve
    nouns, not callers" and explicitly guards against backsliding into
    persona-based routing.
  - [ADR-0015](ADR-0015-router-regression-L1.md) — canary pulse,
    `expected_questions`, reconciliation. Those were deferred. This ADR
    promotes them from "nice to have" to **required**, because the
    artifacts they protect are now load-bearing.
  - [ADR-0006](ADR-0006-datahub-proposal-inbox.md) — DataHub → Neo4j
    one-directional sync. That is the predicate-graph half of the
    two-pipeline integrity contract here.
  - [ADR-0018](ADR-0018-symmetric-spo-routing.md) — symmetric routing and
    the Neo4j (S,P) compatibility reasoner. This ADR closes the two
    soundness holes ADR-0018 left open: the N=1 shortcut and the
    UNKNOWN-subject path.
  - [ADR-0016](ADR-0016-memory-boundary-revised.md) — "read from the
    system-of-record; don't manufacture." Same discipline applied to the
    ontology: it is authoritative, and hand-seeds are band-aids, not state.
  - [ADR-0011](ADR-0011-multi-spo-routing.md) — multi-SPO / chained routing
    (deferred). Owns the composition design this ADR defers to; its
    `/find_path` is where the object (O) re-enters routing as the
    output→input join key between hops.

## Context

### The frame we keep losing and re-deriving

The mesh does not have a "which layer (Jena / Neo4j / DataHub) does this
question belong to?" problem, even though several design conversations have
spent real energy there. It has a smaller, more robust problem:

> **Resolve the subject noun. Ask the graph which predicates are reachable
> from that noun's class chain. Each reachable predicate names its own
> backend. Dispatch there.**

Under this frame layer-discrimination is automatic and never classified.
"Lineage" is not a DataHub query *type*; it is the predicate
`(prov:Entity)-[mesh:traceLineage {endpoint=Engine-D}]->(prov:Entity)` whose
registered resolver happens to be DataHub's lineage API. "Diagram" is not a
Neo4j *thing*; it is `(mro:WorkInstruction)-[mesh:queryKnowledgeGraph
{endpoint=Engine-E}]->(...)`. The subject's neighborhood contains only the
predicates that make sense for it, and each predicate carries its endpoint.
**You never classify a layer. You resolve a noun and read an edge.**

### The trigger

An agent, while "optimizing the routing graph," collapsed the S-P-O model to
P-only — it deleted the subject/class structure and kept only verb edges.
The visible symptom: "show me the diagram for a work-instruction step"
misrouted to DataHub-as-lineage. With the subject (`WorkInstruction`) gone,
all the router had left was "this verb looks lexically like trace/source,"
and BM25 over verb synonyms cannot tell substrate fit from word overlap.
ADR-0018's addendum restored subject grounding and the (S,P) compatibility
filter — the correct fix.

But recovering the *mechanism* exposed that the *substrate* it runs on has no
protection and is currently empty on both sides:

1. **The noun graph is unpopulated.** The ontologies were wiped; ingestion
   hasn't reloaded them. Until it does, subjects resolve to `UNKNOWN` and the
   router runs on its fallback path far more than intended.
2. **The predicate graph is unreliably populated.** Two verbs
   (`enumerateCatalog`, `analyzeDataset`) were missing from the Weaviate
   `Predicate` corpus and were hand-seeded via the REST API because the
   canonical path (`register_engine_to_mesh() → DataHub → doc-tools sensor →
   Neo4j/Weaviate`) dropped records between deploys.
3. **The protections that would catch (1) and (2) are all deferred** —
   ADR-0006's reconciliation asset, ADR-0015's canary + `expected_questions`.

The wipe and the dropped registration are the *same class of failure*: the
two graphs the router depends on are neither reliably populated nor
continuously validated.

### Two graphs, separately populated — the distinction that prevents the wipe

Routing correctness rides on **two distinct graphs in Neo4j**, fed by **two
distinct pipelines**, plus a third optional graph:

| Graph | Contents | Populated by | Role |
|---|---|---|---|
| **Noun graph (TBox mirror)** | `(:OntologyClass)` nodes + `subClassOf` edges | `ingest_ontology_job` (doc-tools): OWL/TTL → S3 → materialize → Neo4j/Jena | `/resolve` grounds the subject here; `/find_compatible_verbs` walks `subClassOf*` here |
| **Predicate graph (routing registry)** | `(:OntologyClass)-[verb {endpoint_url,...}]->(:OntologyClass)` edges | `register_engine_to_mesh() → DataHub → doc-tools sensor` | `/find_compatible_verbs` returns these; the supervisor dispatches to `endpoint_url` |
| **Instance graph (ABox)** | `(:Instance)-[...]->(...)` physical individuals | operational ingestion (out of scope here) | answers instance questions ("is Hammer 12 Bob's?") |

"Load the ontologies" fixes the **noun graph only**. It does nothing for the
predicate graph, which is why concern (2) is not a separate bug — it is the
other half of the same root cause. **Both graphs must be populated and
validated for any non-fallback route to be correct.**

### The category boundary: definitions are not routing verbs

An ontology object-property (`prov:wasDerivedFrom`, `iof:hasInput`) is a
**definition** — a semantic relation with no endpoint. A routing verb
(`mesh:traceLineage`) is a **tool registration** that carries an
`endpoint_url`. They live in the same Neo4j but are categorically different:
`/find_compatible_verbs` returns only edges where `r.iri IS NOT NULL` and an
endpoint is present. **Ontology properties must never be promoted into
routing edges** — a `prov:wasDerivedFrom` property has nothing to dispatch
to. This is the same category error ADR-0004 already caught once
(`:SERVED_BY`). It is restated here as an invariant because the verb-only
regression is what happens when the boundary blurs.

The practical consequence for the planned `idp`/PROV-O load: PROV-O gives you
`prov:Entity`/`Activity`/`Agent` and derivation *properties* as the
subject-side backbone. It will **not** make Engine O pick DataHub by itself.
For "sources of truth for the sales dashboard" to route to DataHub, three
things must coexist — and PROV-O is only the first:

1. the noun resolves (`idp:Dashboard subClassOf prov:Entity` — note PROV-O
   alone has no "Dashboard"/"Dataset"; a thin `idp` extension must declare
   those as `prov:Entity` subclasses, the same pattern as
   `sustainment_extension.ttl`);
2. a verb exists *with a DataHub backend*
   (`(prov:Entity)-[mesh:traceLineage {endpoint=Engine-D}]->(prov:Entity)`,
   landed via registration);
3. the `subClassOf*` walk connects (1) to (2).

PROV-O delivers (1)'s backbone and enables (3). It does **not** deliver (2).
Loading PROV-O and expecting DataHub routing without the lineage tool
registered against a PROV class will resolve the subject, find zero
compatible verbs, fall to the generalist, and look like an ontology-load
failure when the registration half was the gap.

## The constraint we want to keep

- **The ontology is the single source of truth for routing, and it is
  authoritative.** What classes exist, how they nest, which verbs are
  reachable — answerable from the graph, not from code, not from hand-seeds.
- **Both graphs must be populated through their canonical, self-verifying
  pipelines.** A registration that doesn't land in *both* stores fails loud.
- **Resolve nouns, never callers or layers.** Persona/domain/intent are not
  routing inputs (ADR-0009).
- **Definitions ≠ routing verbs.** Ontology properties never become dispatch
  edges.
- **Fail toward the honest generalist, never toward a confident specialist
  guess.** Less grounding must mean *more* humility, not less.
- **The substrate has an immune system.** Versioned, diffable, drift-alarmed.

## Decision

### 1. The unifying frame is adopted as an explicit decision

Routing is noun-resolution over the ontology substrate. The three Engine O
legs are: `/resolve` (subject, 1 LLM) → `/find_compatible_verbs` (Cypher, **0
LLM**) → `/classify_predicate` (verb, ≤1 LLM). The middle leg is the graph,
not a model. The two graphs (noun, predicate) and the category boundary
(definitions ≠ verbs) above are normative.

**The object (O) is resolved, not classified.** A registered verb is typed
with `rdfs:domain`/`rdfs:range` (`input_uri`/`output_uri`), so choosing the
edge chooses *both* endpoints at once — the O is the matched predicate's
range, never a separately-classified axis. The user's desired output is
encoded in the *verb*, not in a classifiable object: "show me the *diagram*
for this step" and "show me the *parts list* for this step" share the subject
(`WorkInstruction`) and differ only in verb, each carrying its own range. SP
resolution is therefore complete for single-hop routing. The O re-enters as
an explicit concern in exactly three places, and the router classifies it in
none of them: (a) as the *range* of the matched edge — single-hop, read for
free; (b) as the *output→input join key* between hops in `/find_path` —
cross-engine composition, matched structurally (ADR-0011); (c) as the
*engine's internal business* for intra-domain composition, where Engine E's
smolagents loop selects the artifact and the registry sees only the outer verb
(`mesh:queryKnowledgeGraph`) — encapsulated, invisible to routing. Case (c) is
the most common and the one "why don't we classify O?" is usually really
asking about.

### 2. Contract A — N=1 soundness: cardinality is not fit

**The N=1 shortcut as shipped is a soundness bug, not just an optimization.**
"This subject has exactly one compatible registered verb" means it is the
only *structurally available* option; it does **not** mean it answers *this*
query. An off-topic question against that subject returns the lone verb at
0.99 — confidently wrong, the original failure mode in new clothing.

Decision:

- At N=1, **still call the LLM**, constrained to a two-value enum
  `{the_verb, UNKNOWN}`. The graph supplies the candidate *set*; the LLM
  validates *fit*. This keeps the graph constraint and preserves the
  "or none fit" escape.
- The LLM may be skipped **only** when a verb is registered with an explicit
  `is_default: true` flag for that subject class — never on cardinality
  alone. We do not register defaults today; until we choose to, there is no
  skip.
- Corollary: do not use the *current frequency* of N=1 to judge the combined
  `ClassifyRoute` call's value. N=1 is common only because the graph is
  sparse right now; as coverage grows N≥2 dominates and the combined call's
  value returns. That measurement is deferred until the substrate is loaded.

### 3. Contract B — one-default convergence (the UNKNOWN-subject contract)

The current three terminal branches have their safety **inverted**: no-noun
takes the *unconstrained confident-verb* path while noun-without-verb stops.
That falls to the more dangerous path with *less* grounding, and the
"unconstrained classification" branch is literally the verb-only path that
caused the trigger bug.

Decision: **every outcome that cannot confidently resolve (S,P) to a
registered, compatible verb converges on the flagged Engine A generalist
(ADR-0008). One default, several roads to it.**

| Case | Old behavior | New contract |
|---|---|---|
| No subject resolved (`UNKNOWN`) | unconstrained verb classification (risky) | **generalist fallback** — never a confident specialist guess without subject grounding |
| Subject valid, zero compatible verbs | hard stop | **generalist fallback** (NO_MATCH *is* the ADR-0008 trigger, not a dead end) |
| Subject valid, N≥1 verbs, LLM picks `UNKNOWN` | (varied) | **generalist fallback** |
| Subject valid, verb confidence < threshold | fallback | **generalist fallback** (unchanged) |
| Subject valid, verb confident + compatible | dispatch | **dispatch specialist** (the only specialist route) |

The "no-noun → unconstrained confident verb-pick" path is **deleted**. With
no subject, the only honest answer is the generalist that announces itself as
such. "We give up" never means a user-facing error; it means "we answer as
the honest generalist."

### 4. Contract C — two-pipeline integrity and substrate governance

The ontology and predicate graphs are now load-bearing for all routing
correctness, so both pipelines must be self-verifying and continuously
validated, and the substrate must be protected.

- **Self-verifying registration.** After `register_engine_to_mesh()`, assert
  the verb landed in **both** Neo4j *and* Weaviate; on mismatch, fail loud
  (raise / alarm), never silently. Hand-seeding via the Weaviate REST API is
  forbidden as a steady state — it hides a broken canonical path
  (ADR-0016-style band-aid). The canonical path is
  `register → DataHub → doc-tools sensor → Neo4j/Weaviate`, and
  `ingest_ontology_job` is the canonical noun-graph path.
- **The ontology is a versioned, protected artifact.** A known-good snapshot
  exists; deploys diff against it; an unexpected drop in class count or
  `subClassOf` edges alarms before it reaches routing. The wipe must be
  *detectable within minutes*, not discovered by a wrong answer.
- **The three Neo4j concerns are conceptually distinct and not editable as
  one blob.** TBox mirror (classes + subClassOf), predicate registry (verb
  edges), ABox (instances) are separate write surfaces. An agent
  "optimizing routing" must not be able to prune the noun graph as a side
  effect of touching verbs. This is the structural anti-regression for the
  trigger incident.
- **The canary is required, not deferred.** ADR-0015's canary pulse
  re-fires a small `expected_questions` set every few minutes and screams
  when a previously-correct route flips. Promoted from deferred to required
  by this ADR, scoped initially to a handful of anchor queries per loaded
  domain.

### 5. Contract D — registered predicates validate their typed range against the substrate

A verb edge is `(input_class)-[verb]->(output_class)`; its `input_uri` and
`output_uri` are the (S,P,O) typing everything downstream relies on —
`/find_compatible_verbs` walks `subClassOf*` *to* the `input_uri`, and
`/find_path` chains `output_uri → input_uri` across hops. If those URIs are
not real ontology classes, both break — silently. ADR-0018 already found this
in the wild: Engine E registered `input_uri: mesh:GraphQuery`, which is not an
`:OntologyClass` in the substrate.

The trap is that the sync MERGEs the endpoint nodes. A typo'd or invented
`input_uri` does not fail — it **creates a phantom `:OntologyClass`** with no
`subClassOf` links to anything real. That phantom is unreachable from any real
subject's class walk, so the verb is never compatible with real queries
(silent NO_MATCH), *and* the noun graph is polluted with junk classes that
corrupt later coverage signals.

Decision: **registration validates that every declared `input_uri` and
`output_uri` resolves to a *pre-existing* `:OntologyClass` in the loaded
substrate; it must never auto-MERGE them into existence.** An unresolved range
type is rejected (or quarantined as `shadow=true` per ADR-0015's quarantine
mode) with a loud, specific error naming the offending URI — never accepted
and silently MERGEd. This is the registration-side counterpart to Contract C:
Contract C checks the edge *exists* in both graphs; Contract D checks the
edge's *endpoints are real*. It is also the hard precondition for ADR-0011
composition — `/find_path` traversing unvalidated ranges traverses garbage.

**Registration identity is the pair `(verb_iri, _tool_urn)`, not the bare
`verb_iri`.** A verb may be legitimately registered against more than one
subject — by more than one engine (the phone-book pattern of ADR-0006's
v0.2 amendment: Engine D + Engine E both register `mesh:resolveInstance`)
or by the same engine against multiple resolver-target subjects (the
multi-registration pattern: Engine E registers `mesh:queryKnowledgeGraph`
against both `MRO/WorkInstruction` and `mro:ProcedureStep`, with the
dedup rule below resolving which entry the LLM sees at request time).
Substrate identity, gateway MERGE match-keys (doc-tools `a44b9fb`), and
any test that pins "verb X is typed against subject Y" must key on the
pair; keying on `verb_iri` alone collapses multi-registrations onto
last-write-wins and silently changes which provider answers.

### 5a. Contract D addendum — the multi-registration dedup rule

When a single `verb_iri` has multiple registrations (multi-provider OR
multi-input-uri from the same provider), `/classify_predicate` MUST
present exactly **one enum entry per `verb_iri`** to the LLM. The entry
shown is the candidate whose `input_uri` is **most-specifically
compatible** with the resolved subject:

1. **Exact match** — `input_uri == resolved_subject_uri`. Wins
   unconditionally.
2. **Nearest ancestor** — `input_uri` is reachable from
   `resolved_subject_uri` via `subClassOf*` in the fewest hops. Wins
   over more-distant ancestors.
3. **Any** — if no ancestor relationship exists, pick the first
   candidate stably (first-seen-index in the substrate query).

This rule lives in `/classify_predicate` (the routing layer), not in
the substrate. The substrate stores all valid registrations; the
routing layer chooses which one the LLM sees for THIS subject. The
routing layer's choice is not authoritative — the LLM can still refuse
on substrate grounds (Contract A's "let the LLM refuse on substrate"
remains the safety floor). The dedup rule is an *ergonomics* fix: it
prevents the LLM from being asked to choose between
`verb_iri=mesh:queryKnowledgeGraph (against WorkInstruction)` and
`verb_iri=mesh:queryKnowledgeGraph (against ProcedureStep)` when both
were the same capability and the dispatcher will use the same endpoint
either way.

The incident that named the rule: `0b0c33e` (2026-06-12). Engine E
shipped a second registration of `mesh:queryKnowledgeGraph` against
`mro:ProcedureStep` (the resolver lands there for "maintenance steps"
queries that have no `subClassOf` ancestors). BAML's `TypeBuilder`
dedupes enum values by name and the second `add_value(verb_iri, ...)`
silently overwrote the first's `description`; the LLM then refused for
`WorkInstruction` subjects ("operates on ProcedureStep, but subject is
WorkInstruction"). Pre-dedup, the fix would have been to dedupe
descriptions at the BAML layer — which forces the routing decision
into BAML's prompt-string layer rather than its enum-membership layer.
Post-dedup, `/classify_predicate` resolves which registration the LLM
sees BEFORE building the enum, and the BAML layer never sees the
collision.

### 6. The `idp`/PROV-O binding is the reference pattern

`idp` uses PROV-O as its conceptual backbone: a thin `idp` extension declares
`Dashboard`, `Dataset`, etc. as `prov:Entity` subclasses, and the
lineage/lineage-source tools register as PROV-shaped verbs
(`(prov:Entity)-[mesh:traceLineage {endpoint=Engine-D}]->(prov:Entity)`).
DataHub's lineage model maps cleanly onto `wasDerivedFrom`, making this a
clean, non-brittle binding. This is the template for binding any backend to
the substrate: backbone ontology for the nouns, tool registration for the
verbs, never the ontology property as the route.

## Consequences

**Wins:**

- Layer-discrimination stops being a classification problem; it is a
  side-effect of noun resolution. The trigger bug becomes structurally
  impossible once the subject is grounded.
- The "confidently wrong" failure mode is closed on both fronts: N=1 now
  validates fit, and the no-subject path can no longer emit a confident verb.
- The wipe and the dropped-registration failures become *detectable* (canary
  + snapshot diff + self-verifying registration) rather than discovered by
  users.
- One routing default. Three terminal cases collapse to "specialist if and
  only if confidently grounded; generalist otherwise."
- Invalid registrations fail at the door instead of creating phantom ontology
  classes that silently make a verb unroutable and pollute the noun graph.

**Costs:**

- **Latency: 1–2 LLM calls per routing decision** — `/resolve` (1) +
  `/classify_predicate` (1), with `/find_compatible_verbs` adding only Cypher
  (~5–15 ms). N=1 is now 2 (was 1) because we validate fit. Per the stated
  "accuracy over latency" preference, this is the accepted trade. The
  combined `ClassifyRoute` call (ADR-0018 follow-up) can later bring this to
  1; defer until the substrate is loaded and the cost is measurable on a real
  N-distribution.
- **Governance work is now mandatory, not optional.** Snapshot/diff tooling,
  registration self-verification, and the canary are required before this is
  "done." That is real effort the deferred ADRs let us skip.
- **`expected_questions` authoring** has a per-domain cost (ADR-0015's
  biggest line item), now incurred at least minimally.
- **Registration is stricter (Contract D).** A verb whose `input_uri`/
  `output_uri` aren't already in the loaded ontology can no longer register —
  so ontology load must precede (or co-deploy with) engine registration, and
  the existing sloppy registrations (Engine E's `mesh:GraphQuery`) must be
  fixed before they validate. A one-time cleanup cost that prevents a
  recurring silent-misroute class.

## Alternatives considered

- **Layer-classification router** ("classify the question into T-Box /
  A-Box / physical, then route"). Rejected. It is the problem the predicate
  graph already dissolves; it reintroduces an N-way classifier (the thing
  ADR-0009 retired) and the substrate-fit blindness that BM25-over-verbs had.
  The Gemini-thread "Semantic Intent Decomposition / Plan-and-Execute /
  Semantic Capability Registry" framings are ADR-0004 under new names.
- **Persona "double-lock" routing.** Rejected outright — directly contradicts
  ADR-0009, which sunset persona as a routing axis. Routing on "who is
  asking" is exactly the impedance mismatch we removed.
- **Keep the N=1 cardinality shortcut.** Rejected. Cardinality ≠ fit; it
  re-opens the confidently-wrong hole. An explicit `is_default` flag is the
  only sound way to skip the LLM.
- **Keep the no-subject unconstrained-confident path "for coverage."**
  Rejected. It is the verb-only regression. Coverage for unknown subjects is
  the generalist's job, announced as such — not a confident specialist guess.
- **Treat the ontology as a mutable unversioned blob (status quo).**
  Rejected. An artifact that an agent can silently wipe, with no snapshot to
  diff and no alarm, is the single largest source of the brittleness this ADR
  addresses.
- **Hand-seed predicates as a steady state.** Rejected. Masks a broken
  canonical pipeline; the next deploy drops verbs again.

## Open items

- **Default-verb semantics.** Is there ever a legitimate per-subject default
  verb, and if so how is `is_default` authored and governed (one per subject
  class? conflicts?)? Decide before any N=1 LLM-skip is enabled.
- **Cross-layer composition is owned by ADR-0011, not re-opened here.**
  Chained, data-dependent routing (output→input across hops via `/find_path`)
  is ADR-0011's deferred design space, with Engine A generalist as its
  documented v1 fallback. This ADR defers to it rather than restating the
  question. One dependency to flag forward: ADR-0011's `/find_path`
  correctness is gated on **Contract D** — until `input_uri`/`output_uri` are
  validated real classes, path traversal chains garbage. Fix the range types
  before un-deferring ADR-0011.
- **Multi-output from one (S,P).** ADR-0011's composition keys on the user
  naming *two distinct entities* (start + end), so its `/find_path`
  disambiguation cannot see the case where one subject and one verb admit
  *multiple user-distinguishable outputs* differing only in which slice of the
  range is wanted ("diagnose this symptom" vs "diagnose this symptom *and tell
  me which part to order*"). If the ontology carries one verb per (subject,
  desired-output) pair, SP resolution covers it silently (the O-difference
  surfaces as a P-difference); if not, SP is genuinely ambiguous and the O has
  to disambiguate. Probe whether this exists once the substrate is loaded —
  it is the single-hop residue ADR-0011 does not cover.
- **Snapshot storage + diff tooling.** Where the known-good ontology snapshot
  lives and what diffs trigger an alarm vs a hard block.
- **`expected_questions` anchor set.** The minimal per-domain corpus the
  canary fires; authoring discipline per ADR-0015's "survey before mint."
- **Engine E grounding-rule + shared-Mem0 gating** (carried from ADR-0016) is
  adjacent: re-enabling Engine E interacts with the substrate's domain scope.

## Out of scope

- The specific ontology contents and which OWL/TTL files load — that is the
  ingest script, not this decision. (This ADR governs *that the substrate is
  loaded, validated, and protected*, not *what is in it*.)
- ABox / instance population strategy.
- Replacing Neo4j, Jena, or DataHub as backends.
- The combined `ClassifyRoute` optimization (ADR-0018 follow-up; revisit
  post-load).

## Indicators for revisiting

- **`UNKNOWN`-subject rate stays high after a full ontology load.** Means the
  noun graph is undercovered for real query phrasings — expand the backbone
  ontologies or the thin domain extensions, don't loosen the convergence
  contract.
- **`no_compatible_verbs_in_neo4j` rate sustained > ~5%** (ADR-0018's signal)
  — a registration gap: engines aren't planting edges, or the `subClassOf`
  bridge to a verb's `input_uri` is missing.
- **Canary flips with no intentional change** — drift in the predicate corpus
  or an embedding/model swap; triage from the ADR-0015 audit record.
- **N≥2 becomes the common case** — re-measure the combined `ClassifyRoute`
  call; its value returns as the substrate matures.
- **Snapshot diff alarms fire during normal operation** more than rarely —
  either the substrate is being edited through non-canonical paths, or the
  TBox/registry/ABox separation isn't actually enforced.
- **Phantom `:OntologyClass` nodes appear** (classes with no `subClassOf`
  edges and no ingestion provenance) — Contract D is being bypassed; a
  registration is MERGEing invented range types instead of validating them
  against the loaded substrate.
