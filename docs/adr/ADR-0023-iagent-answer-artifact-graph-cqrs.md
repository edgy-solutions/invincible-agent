---
status: Proposed
date: 2026-06-26
deciders: Platform team
---

# ADR-0023 — iagent AnswerArtifact as a graph-native CQRS object

## Status

Proposed (2026-06-26).

## Related

- [ADR-0004 — Predicate-graph routing](ADR-0004-predicate-graph-routing.md):
  the routing decision the artifact records as a `ROUTED_AS` edge
  is the same `(verb, input_uri, output_uri, domain, persona)`
  decision this substrate already produces. The artifact captures
  it; this ADR doesn't redefine it.
- [ADR-0017 — Presentation-as-Predicate](ADR-0017-presentation-as-predicate.md):
  the rendered output (`archetype` / `component_uri` / payload) the
  artifact stores is the result of the presentation predicate
  lookup ADR-0017 introduced. The artifact persists what
  presentation already produces.
- [ADR-0019 — Ontology routing substrate](ADR-0019-ontology-routing-substrate.md):
  the same graph-native substrate the artifact node lives in.
  Verbs are edges; INSTANCE_OF is an edge; ROUTING is structured.
  The artifact's typed edge vocabulary inherits this discipline —
  not a property bag, not an untyped node.
- [ADR-0009 — Sunset classification axes](ADR-0009-sunset-classification-axes.md):
  the persona split applies: the artifact carries both the
  user-side persona it was produced for AND the answerer-side
  persona that produced it, because these are independent facts
  about the artifact and conflating them re-creates the class of
  bug ADR-0009 closed.
- `[[canvas-overwrite-lies]]` — the symptom this ADR addresses.
  The canvas shows only the latest artifact, so prior answers look
  regressed (or disappear) when a new query lands. The cause is
  that no durable artifact object exists; the cure is exactly
  what this ADR rules: artifacts as first-class graph-native
  objects with an offline-first read projection.
- `[[ui-contract-assumed-not-published]]` / `[[ui-surfaces-wrong-path]]`:
  the read-side projection schema this ADR introduces is the
  contract surface those memories ask for — published from one
  place, not guessed at by each consumer.
- `[[pingsso-claim-gap]]` — the user-side persona modeled on the
  `PRODUCED_FOR` edge below is downstream of what PingSSO actually
  asserts in the JWT today. Until claim expansion lands, the edge
  is populated thinly (`user_id`, `is_authenticated`) with the
  persona / entitled-domain fields nullable. Modeling the slot
  now means the schema doesn't have to change when claims expand.

## Context

### Where we are now

The UI is one-shot: each new question replaces what's on the canvas.
The user loses their last answer, then their second-to-last, etc.
There is no durable, recall-able, arrangeable artifact for "the
answer to this question." A professional workspace can't be built
on top of a UI that throws away its own state every turn.

The system underneath is graph-native: Neo4j is the substrate;
relationships are typed edges; routing is a structured decision;
the presentation choice is a registered predicate; ontology is
the schema layer. The substrate is ready to carry first-class
artifact objects with relationships. The UI's one-shot behavior is
not a substrate limitation — it's a missing object.

### What changed (and why the model can be simpler than two turns ago)

Prior framings of "durable answer-artifacts" were entangled with
openddil — the assumption was that cortex would adopt openddil's
Expand/Contract DDIL discipline for the read-model, and the
artifact would have to fit inside that. That entanglement is
cleared. The data-model decision for cortex's artifacts is now
self-contained: cortex chooses its own schema, its own read-side
shape, its own projection seam — and openddil overlap (shared UI
components, shared services) lives separately at the
component/service layer, not at the data-model layer.

This buys the meaningful simplification this ADR ratifies: a
self-contained CQRS pair, with cortex governing both halves.

## Decision

The iagent `AnswerArtifact` is a first-class **graph-native CQRS
object**: Neo4j on the write side as source of truth for the
artifact node and its typed edges; ElectricSQL on the read side as
the durable, offline-first-capable projection the UI canvas
consumes. CQRS, self-contained to cortex.

### Write side: Neo4j artifact node + typed edges

The `AnswerArtifact` is a Neo4j node. **Properties** carry what is
intrinsically the artifact's:

- `id` — stable identifier (URN-shaped, mesh namespace).
- `created_at` / `updated_at` — timestamps.
- `question` — the raw user-question text PLUS the resolved intent
  (subject, verb, parameters) as a structured sub-property. The
  raw text is preserved because reformulation is part of the
  artifact's value; the resolved intent is preserved because
  re-running the resolution would not reproduce the historical
  answer.
- `rendered_output` — the archetype / component_uri / payload
  produced by the presentation predicate lookup. Payload can be a
  property if small (table summary, chart spec) or a reference to
  a related node if large (full result set). The size discriminant
  is a schema choice the implementing PR settles, not this ADR.
- `valid_as_of` — the timestamp at which the substrate the artifact
  was grounded against was sampled. Semantically the "as-of" of
  the ground truth this answer reads. Often coincides with
  `created_at` but they're distinct facts: `created_at` is when
  the artifact was made; `valid_as_of` is the time-point the
  grounding represents. They diverge when an artifact is created
  from a deliberately-historical snapshot (a "Q3-2025 revenue"
  artifact created today carries `valid_as_of` of Q3-2025 close).
  Required at creation; what makes freshness checkable.
- `valid_until` — OPTIONAL. The point at which the artifact's
  validity is known to lapse. Set when the answer has a natural
  expiry (current sprint status expires at sprint end; "who's on
  call" expires when the rotation changes; "what was Q3 revenue"
  has no expiry). Null when no natural expiry applies; freshness
  is then computed against grounding instead (see the
  "Freshness as the artifact's stateful dimension" subsection
  below).

**Edges** carry what the artifact is *connected to*. The
substrate is graph-native; relationships are edges:

- `(:AnswerArtifact)-[:PRODUCED_BY]->(:Actor)` — provenance,
  **answerer-side**. Actors are either users or agents. Agent
  actors carry `version`, `endpoint`, `code_hash` as properties on
  the Actor node (or on the edge — the implementing PR settles
  which; the discipline is that they ARE captured). This edge
  identifies **who did the answering** — the agent (or user) that
  produced this artifact. Combined with `ROUTED_AS` below, it
  carries the **answerer-side persona** per ADR-0009: the persona
  the engine occupied when it answered (e.g.,
  `owner_persona: DATA_STEWARD` on the routing).
  **Capture-at-creation-or-lose-forever**: there is no path to
  recover this after the fact.
- `(:AnswerArtifact)-[:PRODUCED_FOR]->(:Actor)` — the requesting
  user, **user-side**. Carries the **user-side persona** per
  ADR-0009 — the persona / role / entitlements of who asked.
  ADR-0009 makes this a separate fact from the answerer-side
  persona on `PRODUCED_BY`; **conflating them is the exact bug
  ADR-0009 closed**. The two edges have different shapes —
  `PRODUCED_BY` typically points at an agent Actor with
  `code_hash` / `version`, `PRODUCED_FOR` points at the requesting
  human user with role / entitled domains — and different facts on
  them. Modeling both edges explicitly is what enforces the
  ADR-0009 anti-conflation discipline at the schema level rather
  than leaving it to implementer judgment. **Capture-at-creation**.

  *Today's claim gap*: the user-persona is downstream of what the
  PingSSO JWT actually asserts, and per `[[pingsso-claim-gap]]`
  the JWT today lacks `user_persona` / `entitled_domains` claims.
  Modeling the edge now reserves the slot; populating it richly
  waits for the JWT claim expansion. In the interim the edge
  carries `user_id` and `is_authenticated`; persona / entitlements
  fields stay nullable, and the implementing PR's read-side
  projection treats null persona as "unknown user persona" rather
  than as a default value (which would silently mask the gap).
- `(:AnswerArtifact)-[:DERIVED_FROM]->(:AnswerArtifact)` — inter-
  artifact lineage. Follow-up questions, refinements, related
  answers. **Also capture-or-lose-forever**: workspace grouping
  ("the conversation about region breakdowns") depends on having
  this edge at creation time; reconstructing it later from text
  similarity is a different (and weaker) thing.
- `(:AnswerArtifact)-[:ROUTED_AS]->(:RoutingDecision)` OR routing
  as artifact properties — the routing decision (subject, verb,
  confidence, handler, `owner_persona`). The substrate already
  produces a structured routing object; this ADR records it. The
  routing decision is where the **answerer-side `owner_persona`**
  (per ADR-0009) lives durably — the persona the engine occupied
  when answering, distinct from the user-side persona on
  `PRODUCED_FOR`. Cardinality and reuse decide node-vs-property
  (a routing decision shared by many artifacts argues for a node;
  a one-of-one decision argues for properties). The implementing
  PR settles this when the first reuse case lands.
- `(:AnswerArtifact)-[:CITES]->(:Source)` — the sources / grounding.
  Sources are likely their own nodes because they're reusable: many
  artifacts may cite the same source URN, the same DataHub asset,
  the same paragraph. `Source` carries its own URN, type, and
  display metadata; `CITES` carries the artifact-specific evidence
  (span, quote, confidence). One `Source` node, many `CITES` edges
  pointing at it.

**Reserved standards edges** (defined now, instantiated per-demand
when the standards are integrated — see ADR-0024):

- `(:AnswerArtifact)-[:PRODUCED_BY_PROCESS]->(:BpmnProcess)`
- `(:AnswerArtifact)-[:CONFORMS_TO]->(:OdcsContract)`
- `(:AnswerArtifact)-[:IS]->(:OdpsDataProduct)`
- `(:AnswerArtifact)-[:WITHIN]->(:CalmComponent)`

These are reserved as **edge vocabulary**. The target node types
will be instantiated when each standard integration lands. Naming
them now in the ADR keeps the schema honest: when a future PR
needs to attach an artifact to a BPMN process, the edge type
already exists; the PR doesn't get to mint an ad-hoc one.

### The discipline (carry this into the ADR's authority)

The edge vocabulary is **typed and defined** — same rigor as the
verb-edges (ADR-0004) and `INSTANCE_OF` (ADR-0019). Which edges
exist, what they connect, what they mean — that's the schema. No
untyped node. No relationship-as-property-bag. The node has defined
properties; the edges have a defined vocabulary. Adding a new
relationship to the artifact's neighborhood requires adding a new
edge type (and reasoning about why an existing one wasn't enough),
not stuffing it into an untyped slot.

### Freshness as the artifact's stateful dimension

The artifact IS stateful — and the state it carries is
**validity / freshness**, not generation-status (which is
provenance-at-creation plus transient UI) and not workflow-position
(which is BPMN's concern, deferred to ADR-0024). Three
state-concepts converge on the artifact; only one of them is
intrinsically the artifact's:

| State concept | Whose concern | Where it lives |
|---|---|---|
| Workflow-position ("step 3 of the approval process") | The process model | `PRODUCED_BY_PROCESS` edge → `BpmnProcess` node (ADR-0024, deferred) |
| Generation-status ("still being produced / done / failed") | Provenance + transient UI | At creation, on `PRODUCED_BY` (succeeded) or as a transient UI signal while the artifact doesn't-yet-exist. **NOT modeled as an artifact property.** Once the artifact exists, "it was produced successfully" is a fact, not a changing state. |
| Validity / freshness ("is this answer still true") | The artifact itself | `valid_as_of` / `valid_until` properties + checkability against captured grounding. **The artifact's genuine stateful dimension.** |

The reason validity is intrinsic to the artifact (and the other two
aren't) is that an answer in this system is **grounded in a
substrate that changes**. "Who owns the Customer 360 dashboard?"
→ `alice@company.com` was true against the DataHub state at the
moment the answer was produced; ownership may have changed since.
The answer has a validity that decays — fresh at creation,
questionable after some time, stale when the grounding moves.
That's not workflow (BPMN) and not generation (provenance) — it's
the answer's own relationship to a mutating ground truth over
time, which is the answer's property and is stateful (fresh →
aging → stale → invalid).

#### Why this architecture can do freshness precisely

Because every artifact captures **exactly what it was grounded in**
— `CITES` edges to `Source` nodes (URNs) plus the `ROUTED_AS`
decision recording the verb and target — the system can re-derive
freshness against the live substrate. "This answer cited
`urn:li:dashboard:(superset,customer_360)`'s ownership; has that
ownership changed since `valid_as_of`?" A generic chatbot can't
answer that (it doesn't know what its answer depended on). This
one can, because the grounding is captured at creation.

That makes validity here different from a generic TTL: not
"expires in 24h" but "valid until its specific grounding changes."
The TTL shape (`valid_until`) is supported for cases where it
applies (natural expiries, sprint windows), but the more powerful
shape is grounded-freshness checked against the substrate the
artifact already recorded.

#### Staleness contract — the honest-degradation discipline applied

This is the same staleness discipline `[[feedback-honest-failure-as-demo]]`
and `[[feedback-verification-must-fail]]` codify, applied to
grounded answers: an answer has a freshness, and the honest move
is to surface when an answer may be stale rather than present a
month-old grounding as current truth. Conceptually parallel to
openddil's offline-COP staleness banner (which honestly flags
when synced telemetry is stale) — same discipline, independent
implementations, not a shared component. Cortex owns its
answer-validity model; openddil owns its telemetry-staleness
model; both honor the same principle.

#### Why this matters for the durable-workspace vision

In a workspace where answers are durable and recall-able, stale
answers are a hazard. A user pulls up a three-week-old "who owns
this dashboard" answer and acts on it, not realizing ownership
changed. **Validity / freshness is what makes durable artifacts
trustworthy in a workspace**: durable answers that show their age
and can be refreshed, rather than durable answers that silently
become wrong. A workspace of answers with no freshness signal is
a workspace of possibly-stale answers presented as current — the
confidently-wrong failure scaled up. The freshness model prevents
that, which is exactly what makes a durable canvas safe rather
than a liability.

### Read side: ElectricSQL projection from Neo4j, for the UI canvas

The canvas needs to render artifacts fast and offline-first. That's
the read-projection. The artifact's **display form** —
flattened/denormalized for rendering: the question, the routing
summary, the sources list, the rendered payload, assembled into one
read-row — projects into the Electric-synced read-model the canvas
consumes.

This makes the canvas **durable** (artifacts persist; the
"vanished prior answer" symptom is gone) and gives a **syncable**
foundation for the eventual collaborative workspace (multi-user,
multi-device, conflict-free sync — Electric's design center).

Neo4j is the source of truth for relationships and routing
structure; the Electric-fronted store is the read-model for the
UI. CQRS, self-contained to cortex.

### The genuine design seam this ADR names

Electric syncs from Postgres — it's a Postgres-shape sync
technology. "ElectricSQL projection from Neo4j" therefore means:

```
Neo4j (write/graph) ─▶ Neo4j→Postgres projector ─▶ Postgres ─▶ Electric Shape API ─▶ UI canvas
                                  ▲
                                  └─ THIS is the seam this ADR names
```

The Neo4j→Postgres projection step is a real component cortex must
build. It is cortex's analog of openddil's Restate-exactly-once-apply
step in openddil's own projector. **The ADR names it explicitly so
its existence isn't hidden behind the phrase "Electric projects
from Neo4j."** When the implementing PR lands the projector, it
lands as a named component with its own contract (idempotent apply,
deterministic projection, replay-able from any Neo4j state),
because that's the shape an Electric-feeding projector has to have.

The implementation choices the projector PR settles: change-source
on the Neo4j side (CDC stream vs polling vs txn-log tail), apply
shape on the Postgres side (one table per archetype vs one wide
table with discriminator), and how the projector advertises its
position so consumers can wait for "see-your-write" reads. None of
those choices are in this ADR — the ADR rules that **the seam
exists** and **what shape it has to have**.

### The know-it / defer-it / never-it discipline applied

| What | When | Why |
|---|---|---|
| `id`, timestamps, `question`, `rendered_output`, `valid_as_of`, optional `valid_until`, `PRODUCED_BY` (with agent `code_hash`/`endpoint`, answerer-side persona via `ROUTED_AS`), `PRODUCED_FOR` (user-side persona slot, thinly populated until PingSSO claim expansion), `DERIVED_FROM`, `ROUTED_AS` (with `owner_persona`), `CITES` | **Know it, model now (typed).** | Empirically validated by weeks of UI behavior; capture-or-lose-forever for provenance + lineage; dual-persona enforces ADR-0009 at schema level rather than in prose; `valid_as_of` + grounding (`CITES`) is what makes freshness checkable. |
| `PRODUCED_BY_PROCESS` (BPMN), `CONFORMS_TO` (ODCS), `IS` (ODPS), `WITHIN` (CALM) | **Defer, reserve vocabulary, instantiate per-demand.** | Standards aren't all integrated yet. Reserving edge types now keeps the schema honest when each standard lands without forcing the integration today. ADR-0024 carries the composition reasoning. |
| Workflow-state ("step 3 of the approval process") as an artifact property | **Defer to the BPMN edge** (`PRODUCED_BY_PROCESS` → `BpmnProcess`), ADR-0024. | That's BPMN's concern; the artifact references the process and reads the process's state, doesn't carry it. |
| Generation-state as an artifact property (`status: pending\|streaming\|complete\|failed`) | **Never on the artifact.** | Generation-status is provenance-at-creation ("did it succeed" on `PRODUCED_BY`) plus transient-UI (the canvas shows "generating…" while the artifact doesn't-yet-exist). Once the artifact exists, "produced successfully" is a fact, not a changing state. Modeling it as artifact state would create a stateful field that never genuinely transitions (the artifact is born complete or it isn't born) and would confuse with the validity/freshness state that IS intrinsic. |
| Untyped node, property-bag relationships, generic `standards_refs` list, free-text `metadata` blob | **Never.** | Killed in prior discussion. These re-introduce the assumed-contract class (ADR-0017) and the relationships-as-fields anti-pattern that fights the graph-native architecture (ADR-0019). |

## Alternatives considered

### Field-bag with reference slots

Treat the artifact as a row with fields for `provenance_actor_id`,
`derived_from_artifact_id`, `routing_decision_json`,
`citations_json`. No edges; everything is a property or a JSON
column.

**Rejected.** Fights the graph-native architecture. Relationships
become opaque references that can't be traversed (or worse, can
be traversed by application code re-implementing graph traversal
in SQL). Loses every property a graph substrate gives you for free
(reachability queries, multi-hop lineage, "show me everything that
cites this source"). Re-introduces the assumed-contract class — the
JSON columns become un-versioned, un-validated, un-published
contracts that every consumer guesses at.

### `standards_refs: List[str]` untyped slot

A single property on the artifact, holding a list of URNs that
point at "whatever standard-flavored thing this artifact relates
to." Lazy, ostensibly future-proof.

**Rejected.** Loses relationship semantics — `PRODUCED_BY_PROCESS`
and `CONFORMS_TO` have different meanings; collapsing them into
one untyped list throws that away. Loses target-type
discrimination — a BPMN process node and an ODCS contract node are
different things and the system needs to know which one an edge
points at. Becomes a typed-blob trap: the moment any consumer needs
to filter by relationship type, the parsing logic has to materialize
the type information that was discarded at write time.

### App-store separate from the graph

Put the artifact in a relational app-store (or document store)
outside Neo4j; keep Neo4j for the substrate (ontology, routing,
verbs) only.

**Rejected.** Creates a second data model with its own seam to the
graph. Workspace queries that span "the answers about region
breakdowns plus the verbs they used" now traverse a graph-to-store
boundary that the implementation has to manage. Single-source-of-
truth fails: the artifact's `ROUTED_AS` relationship lives in
the app-store while the routing target lives in the graph, and the
two can drift. The substrate is already graph-native; making
artifacts live elsewhere costs the property we already have.

## Consequences

### What this unlocks

- **Workspace queries become graph traversals**, native: "show me
  every answer that cited this source," "show me the lineage of
  this artifact's follow-ups," "show me all artifacts produced by
  this agent version" — all single-Cypher queries on the substrate
  the system already runs.
- **Closes `[[canvas-overwrite-lies]]`**: the canvas becomes a
  view over a collection of durable artifacts, not the latest one.
  Prior answers persist; new answers add to the collection rather
  than replacing what's there.
- **Offline-first / syncable foundation**: the Electric projection
  is what later carries collaborative editing, presence,
  cross-device sync, conflict-free workspace operations. Building
  it on the projection now means the collaboration arc doesn't
  need to revisit the data model.
- **Provenance and lineage are first-class**, queryable, and
  capture-at-creation. The system can answer "which agent
  produced this and at what version" with a graph traversal, not
  log archaeology.

### What this costs

- **The Neo4j→Postgres projector is a new component**. Idempotent
  apply, deterministic projection, position advertisement so
  consumers can wait for see-your-write reads. Non-trivial, but
  the shape is well-understood and the component scope is bounded.
- **The write-path on every answer touches Neo4j** plus the
  projector plus Electric — a longer critical path than the
  current "render to UI and forget" shape. Latency budget needs
  to be measured before the first writes hit production load.
- **Schema migrations now span both sides** of the CQRS pair. The
  Neo4j edge vocabulary and the Postgres projection schema have to
  evolve together; the projector PR has to land with a migration
  story that covers both.

### What stays deferred

- **The four standards edges** (`PRODUCED_BY_PROCESS`,
  `CONFORMS_TO`, `IS`, `WITHIN`) are reserved as vocabulary; their
  target nodes get instantiated when each standard integration
  lands. ADR-0024 carries the standards-composition decision.
- **The free-spatial-canvas / tabs / projects UI metaphor**. How
  the user arranges artifacts in their workspace — what the canvas
  view actually looks like as it accumulates — is a UI-arc
  decision, not a data-model decision. The data model supports
  any of those metaphors; the metaphor itself waits for usage
  data and the upcoming UI cleanup arc.
- **Collaborative / HITL operations** on the artifact (multi-user
  edits, comments, annotations, hand-off). Electric's sync layer
  makes these tractable later; this ADR doesn't yet rule on the
  semantics.

### What this ADR explicitly does NOT cover

- **Openddil overlap.** Shared UI components and iagent-service
  reuse with openddil are an openddil-side integration concern
  (openddil imports cortex's UI components and calls cortex's
  services). None of that touches cortex's data model. Openddil
  may ADR that on its side; it's not in scope here.
- **The standards composition** (BPMN / CALM / ODPS / ODCS — which
  standard is authoritative for which concept, how the seams
  compose, artifact-references-never-reimplements). That's
  directional, integrated per-demand, and gets its own ADR.

## Note on ADR-0024 (the standards-composition decision)

Reserved as a separate ADR because it's a different decision with
different reasoning and a different timeline. ADR-0023 (this ADR)
is near-term and rule-able now — the artifact-as-graph-CQRS-node
foundation the UI session builds on. ADR-0024 is directional —
which standards are authoritative for which concepts, how their
seams compose, the discipline that the artifact REFERENCES (never
re-implements) what the standards say. Bundling them would make
ADR-0023 block on settling the standards composition, which it
shouldn't: the artifact-as-graph-node-CQRS decision is rule-able
and buildable now, independent of when each standard gets
integrated.

ADR-0023 reserves the edge vocabulary. ADR-0024 will rule on the
composition reasoning when the first standard pulls in for
integration.

## Open questions for the implementing PR

The ADR rules the schema and the seam; these are questions the
first implementing PR has to settle and are listed here so the PR
doesn't have to re-derive them:

- **Routing decision as edge-to-node vs properties?** Settles by
  the first reuse case (a routing decision shared by N artifacts
  argues for a node; one-of-one argues for properties).
- **Rendered output as property vs related node?** Size
  discriminant; the PR picks a threshold (e.g., < 10 KB inline,
  ≥ 10 KB as a related node) and documents it.
- **Agent metadata on the Actor node vs on the PRODUCED_BY edge?**
  `version` / `endpoint` / `code_hash` — properties of the agent
  (Actor node) vs properties of the act-of-production (edge). The
  PR picks based on whether two artifacts produced by the same
  agent at the same code_hash should share an Actor node (argues
  for node properties) or whether each production is its own fact
  (argues for edge properties).
- **Change-source for the Neo4j→Postgres projector**: CDC
  (Neo4j 5+ has a change-data-capture story), polling, txn-log
  tail. PR picks one with an explicit "why this, not the others"
  paragraph.
- **Postgres projection shape**: one table per archetype, one wide
  table with a discriminator, JSON-payload-with-typed-headers.
  PR picks based on what the canvas's read query shape actually
  needs.
- **Position advertisement**: how the projector publishes its
  Neo4j-position so consumers can wait for see-your-write reads.
  Required for the canvas to feel responsive after a write.
- **Freshness-computation strategy** for validity. The model
  captures `valid_as_of` + the grounding (`CITES` + `ROUTED_AS`),
  so any of three strategies is supported; the PR picks based on
  workspace use patterns:
  - *Static TTL* — `valid_until` is the truth. No substrate
    check. Simplest, but ignores the artifact's captured grounding.
  - *Substrate-change detection* — watch each cited URN's
    relevant state; mark the artifact stale when grounding moves.
    Most powerful (genuine grounded-freshness, uses the captured
    grounding) but requires watching the substrate and an apply
    path for stale-marks.
  - *On-read freshness check* — at display time, re-evaluate the
    grounding against current substrate and label fresh / stale.
    Lazy, no watching needed, but adds read latency. Compose-able
    with TTL (skip the substrate read when `valid_until` is in
    the future and TTL is the contract).
  The model doesn't foreclose any of the three. Worth doing the
  cheapest one first (static TTL where natural expiries apply;
  on-read elsewhere) and growing into substrate-change detection
  for high-value artifacts.
- **User-Actor population shape** in the interim before PingSSO
  claim expansion. The PR settles whether `PRODUCED_FOR` lands
  with `user_persona: null` / `entitled_domains: null` and a
  comment, or whether the field is omitted entirely until claims
  are available. The schema discipline argues for the slot
  existing with explicit-null (so a future claim expansion is a
  populate, not a schema migration); the implementing PR makes the
  call.
