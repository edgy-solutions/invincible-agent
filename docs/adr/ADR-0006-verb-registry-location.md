# ADR-0006 — DataHub as proposal inbox, Neo4j as runtime substrate

**Status:** Accepted
**Date:** 2026-05-29
**Deciders:** Platform team
**Related:**
  - [ADR-0004](ADR-0004-predicate-graph-routing.md) (establishes the
    predicate graph and propose-approve-sync flow)
  - [ADR-0005](ADR-0005-verb-and-concept-namespaces.md) (the namespacing
    each side stores)

## Context

[ADR-0004](ADR-0004-predicate-graph-routing.md) establishes the predicate
graph routing model. The verb registry has two storage sides:

- **DataHub** holds the proposal queue (`aiTool` and `glossaryTerm`
  entities, the `proposeTerms` mutation history, the human-approval
  state for HITL registrations).
- **Neo4j** holds the runtime graph (`(:OntologyClass)-[verb {...}]->(:OntologyClass)`
  edges that Engine O queries on every `/find_tool` and `/find_path`
  call).

doc-tools' `DataHubSensorComponent` syncs from DataHub to Neo4j on
approval — already proven for Datasets, cloned for AITools by ADR-0004's
Step B.

ADR-0004 deferred the question: **when DataHub and Neo4j diverge, which
is authoritative?** This isn't a theoretical concern. Operators will
manually edit Neo4j to fix routing during incidents. Sync sensors can
fail or fall behind. Test fixtures may seed Neo4j directly without going
through DataHub. We need a written authority rule.

## Decision

**DataHub is authoritative for the proposal queue.** What's been
proposed, by whom, when, with what reason, what approvals — the
governance history. The propose-approve flow lives entirely in DataHub.

**Neo4j is authoritative for runtime routing.** Engine O `/find_tool` and
`/find_path` read Neo4j only; they never query DataHub at request time.

**The sync flow is DataHub → Neo4j, one-directional, sensor-driven.**
Never the reverse. Neo4j never writes back to DataHub.

When DataHub and Neo4j diverge:

- **DataHub has an approval that hasn't reached Neo4j yet** (sensor
  lag, sync error): the sensor's next poll catches it. If repeated polls
  fail, the asset materialization fails loudly in Dagster and operators
  intervene.
- **Neo4j has an edge that doesn't exist in DataHub** (manual edit,
  test seed, sync from a removed source): the runtime behavior follows
  Neo4j (the routing works), and a periodic *reconciliation asset*
  (deferred — see "Open questions" below) flags the drift for human
  review. The drift is not auto-healed by re-deriving Neo4j from
  DataHub — that would silently remove operator fixes.
- **DataHub has an approved tool that Neo4j doesn't have** (sync never
  ran for this tool): same as the first case; sensor catches up.

## Consequences

**Wins:**

- **Mesh consumers (Engine O, supervisor) only ever read Neo4j.** They
  never need to know DataHub exists. Reduces blast radius of DataHub
  outages: proposals stall, but runtime routing keeps working off the
  last-synced Neo4j state.
- **doc-tools is the only consumer of the DataHub side.** All other
  components see a clean Neo4j interface. Future migrations (e.g., if
  DataHub is replaced) touch only doc-tools' propose path.
- **The governance history lives in DataHub.** Audits, "why was this
  tool registered," "who approved this verb," "what was the reasoning"
  — all answerable from DataHub without spelunking Neo4j relationship
  metadata.
- **Test fixtures can seed Neo4j directly.** Unit tests for routing
  don't need a DataHub instance — they MERGE the edges they need and
  query against them. The propose-approve-sync flow gets its own
  integration tests.
- **One-directional sync is simpler to reason about.** No conflict
  resolution, no merge semantics, no last-write-wins races.

**Costs:**

- **Neo4j outages do affect runtime routing.** Engine O depends on it.
  Mitigation is operational: Neo4j HA configuration, Engine O caches
  recent `/find_tool` results, supervisor falls back to last-known-good
  paths.
- **Drift is possible.** Manual Neo4j edits silently diverge from
  DataHub. The reconciliation asset (below) detects but does not
  auto-fix. Operators have to decide per drift whether to re-propose
  through DataHub or remove the Neo4j-only edge.
- **doc-tools' propose pipeline is a single point of failure for
  *new registrations*.** If doc-tools is down, no new tools land. But
  existing routes keep working.

## Reconciliation asset (deferred to follow-up)

A periodic `reconcile_predicate_graph` Dagster asset:
- Queries Neo4j for all verb edges
- Queries DataHub for all approved `aiTool` entities and their bindings
- Reports drift: edges in Neo4j but not in DataHub, edges in DataHub
  but not in Neo4j
- Does NOT auto-heal. Emits Dagster MaterializeResult with `drift_count`
  and a list; operators triage from Dagster UI.

Specified here in case it's needed, but not part of the initial
implementation (Step B of ADR-0004). Add when the first real drift
incident motivates it.

## Alternatives considered

- **Neo4j as authoritative on conflict, with DataHub as a write-through
  cache.** Rejected. Loses DataHub's governance / proposal-history /
  HITL queue features. DataHub is built for "proposed, under review,
  approved by X, comments by Y" workflows; Neo4j isn't.

- **Bidirectional sync (DataHub ↔ Neo4j).** Rejected. Conflict
  resolution complexity; no clear winner semantics; manual operator
  edits to Neo4j would flow back to DataHub as new "proposals" without
  the normal approval context, polluting the governance history.

- **Read-through to DataHub at runtime.** Rejected. Makes Engine O
  dependent on DataHub availability. Adds latency to every routing
  decision. Caching mitigates but reintroduces the staleness question
  this ADR is trying to settle.

- **Maintain both as equal stores with explicit reconciliation on read.**
  Rejected. Requires a third arbiter; punts the question; adds
  complexity for the rare conflict case.

- **Eventual consistency via event log (e.g., Kafka between DataHub and
  Neo4j).** Rejected for now as over-engineered. The sensor-poll
  pattern works; sub-30s lag is acceptable; revisit if we need
  sub-second propagation later.

## Indicators for revisiting

- **DataHub is deprecated within the organization** or its
  custom-property API becomes unworkable. The propose side moves to a
  small dedicated service (proposed name: `mesh-registry`). The Neo4j
  runtime side is unaffected by the migration — doc-tools changes,
  Engine O does not.
- **Neo4j proves the wrong runtime substrate** (federated graphs needed,
  or full SPARQL/OWL reasoning at runtime). The runtime side migrates
  (likely to Jena or a hybrid). The propose side (DataHub) is
  unaffected.
- **Bidirectional editing emerges as a real need.** Concretely: runtime
  operators routinely need to update edge metadata (latency budgets,
  endpoint URLs) and want those changes to flow back to governance.
  Would warrant a real conflict-resolution design.
- **The reconciliation asset surfaces drift frequently enough to
  matter** (more than a handful per month). At that point the
  one-directional rule may need adjustment, or doc-tools' propose
  flow needs to expose more entry points for operator-initiated
  changes.
