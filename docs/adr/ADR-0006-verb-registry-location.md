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

## Addendum — Gateway v0.2: the mesh-registrar becomes sole writer of AITool predicate edges

**Status:** Proposed (2026-06-12) — pending the rollback-vs-quarantine
fork resolution in the Consequences matrix below. No code lands until
that paragraph is decided.
**Date:** 2026-06-12
**Related:**
  - The original v0.1 mesh-registrar gateway (`agent_fleet/mesh_registrar/`)
    that validates Contract D and emits the DataHub MCP — but does NOT
    write Neo4j or Weaviate directly. That work belongs to the doc-tools
    `aitool_registration_sensor` (`doc_tools/components/aitool_sensor.py`).
  - Recipe v2 / Gate 6 (tests/routing/STATE_RECIPE_V2.md), which surfaced
    two bug classes that motivate this amendment:
      - **Allowlist drift** in `aitool_linker._build_relationship_properties`
        (new gateway-emitted customProperties silently dropped).
      - **Sensor run-key dedup** (content-hash matches → skip), which
        masked a half-applied edge for hours when only one of the two
        stores had the new property shape.

### What this amendment changes (AITool path only)

The v0.1 architecture splits the AITool registration write between two
components:

```
v0.1 (today):
  Engine ─POST manifest─▶ Gateway ─emit MCP─▶ DataHub ─sensor polls─▶ Neo4j edge
                          │                                            +
                          └─ Contract D                                Weaviate row
                             validation (read-only)
```

v0.2 inverts the authority flow so the gateway is sole writer of AITool
predicate edges in **both** runtime stores, and DataHub is downstream:

```
v0.2 (proposed):
  Engine ─POST manifest─▶ Gateway ┬─ Contract D
                                  ├─ MERGE Neo4j edge
                                  ├─ Upsert Weaviate row
                                  ├─ Read-back probe (verify both)
                                  ├─ Enqueue DataHub MCP emit (async)
                                  └─ Return 200 iff substrate verified
```

The doc-tools `aitool_registration_sensor` loses its AITool branch in
the same change (see Decision §3 below). The `DataHubSensorComponent`
that syncs **Datasets** keeps everything — this amendment is scoped
to AITool registrations only.

### What this amendment preserves

- **ADR-0006 §Decision rule 2 — Neo4j is authoritative for runtime
  routing.** Engine O still queries only Neo4j; never DataHub at
  request time. The amendment narrows what's allowed to *write* Neo4j;
  it does not change what *reads* it.
- **ADR-0006 §Decision rule 3 — sync flow is one-directional, never
  Neo4j → DataHub.** v0.2's `gateway → DataHub` write is a fresh
  emit of governance history (proposal record), not a sync. The
  gateway holds the manifest as the source of truth for the
  registration intent; DataHub holds the *record* that the
  registration was attempted, by whom, when, with what reason.
- **DataHub as proposal queue + governance history.** Unchanged. The
  `proposeTerms` mutation, the HITL approval flow, the
  human-in-the-loop queue for sensitive registrations — all still
  there, all still in DataHub. v0.2 only changes that the
  predicate-edge materialization stops *waiting on* DataHub.
- **The reconciliation asset proposal** in §"Reconciliation asset"
  remains relevant — drift between Neo4j and DataHub is now
  expected (the gateway writes Neo4j directly; DataHub emit is
  async; brief drift windows are routine). The reconciler reports
  drift; it does not auto-heal.
- **Dataset HAS_DATA pipeline.** Untouched. Datasets keep their
  sensor-driven sync. The amendment is AITool-scoped because:
  - AITools have a single canonical proposer (the engine itself
    via `register_engine_to_mesh`). Datasets have many proposers
    (DataHub UI uploads, dbt models, manual entries) and the
    "DataHub is the entry point" pattern fits that fan-in.
  - AITools' substrate split (Neo4j edge + Weaviate row) is the
    failure surface this amendment closes. Datasets only write
    Neo4j HAS_DATA edges; there's no symmetric Weaviate write to
    keep atomic.

### What this amendment changes vs. ADR-0006's text

- **§Context paragraph 1 sentence 3** ("doc-tools'
  `DataHubSensorComponent` syncs from DataHub to Neo4j on approval —
  already proven for Datasets, cloned for AITools by ADR-0004's
  Step B.") — split. Dataset sync remains. AITool sync is replaced
  by gateway-direct write per v0.2.
- **§Decision rule 3** ("sync flow is DataHub → Neo4j,
  one-directional, sensor-driven") — narrowed to Datasets. AITools
  flow gateway → Neo4j + Weaviate; DataHub emit becomes async
  governance record.
- **§Consequences "doc-tools' propose pipeline is a single point
  of failure for new registrations"** — partially obsoleted for
  AITools. The gateway becomes the new SPOF for AITool
  registrations, but it's a much smaller surface (no Dagster,
  no sensor polling, no DataHub-search dependency) and its
  failure mode is "engines can't register" which is what every
  registration pipeline's SPOF looks like.

### Consequences — partial-failure matrix

The gateway performs three writes per registration:

- **N** — Neo4j edge MERGE (apoc.merge.relationship on
  `(input_uri, verb_iri, output_uri)` with `_tool_urn` in the
  match key per doc-tools a44b9fb).
- **W** — Weaviate `Predicate` collection upsert (deterministic
  UUID from `verb_iri | input_uri`).
- **D** — DataHub MCP emit (mlModel customProperties record).

**Ordering** within the request path:

1. Contract D validation (read-only check; not a write).
2. **N** — Neo4j MERGE.
3. **W** — Weaviate upsert.
4. Read-back probe: query both stores, assert the registered
   verb is present.
5. Either return 200 (probe passed) or enter partial-failure
   handling (probe failed; see fork below).
6. **D** is enqueued for async emit regardless of N/W outcome
   (governance history of attempts is itself useful data).

**Working priors encoded** (any override needs a written reason):

- *Substrate writes are the gate.* No 200 unless N AND W both
  verified by the read-back probe. This means a degraded
  registration (one store wrote, the other didn't) NEVER
  returns 200 even if the caller can technically route via the
  side that wrote — because the routing layer's two halves
  (Cypher walk + Weaviate hybrid search) would be operating on
  inconsistent state.
- *DataHub emit is governance history, retryable, async, never
  dropped.* D's failure does not block 200 nor 5xx. D is
  enqueued (durable queue), retried with backoff, and on
  exhausted retries lands in an operator-visible dead-letter
  topic. D's success or failure is decorrelated from the
  registration's substrate outcome.
- *Partial substrate success MUST NOT leave a half-registered
  verb routable.* (This is what the fork below addresses.)

The 4 substrate outcome combinations (D rides separately and
always queues, so it isn't a dimension here):

| # | N | W | HTTP | Caller belief                       | Retry semantics                              | Cleanup obligation |
|---|---|---|------|-------------------------------------|----------------------------------------------|--------------------|
| 1 | S | S | 200  | "registered, both stores live"      | n/a (idempotent on identical manifest)       | none               |
| 2 | S | F | **see fork** | **see fork**                | yes, idempotent; same path retried           | **see fork**       |
| 3 | F | S | **see fork** | **see fork**                | yes, idempotent; same path retried           | **see fork**       |
| 4 | F | F | 5xx  | "rejected, no writes landed"        | yes, idempotent                              | none (nothing wrote) |

Cases #2 and #3 are the failure class this amendment exists to
close. The remaining content of the matrix depends on which
arm of the fork the user picks. Both arms preserve the working
priors above.

### Decision needed — rollback vs. quarantine

**This is the design fork I'm leaving for the user per the
assignment's "stop at genuine forks" rule.** Both options
preserve the working priors. Both have real failure modes.
I have a leaning (rollback) and the case for the other
(quarantine) is strong enough that I should not pick alone.

#### Option A — Rollback the half-write

On case #2 (`N=S, W=F`), DELETE the Neo4j edge before returning
5xx. Mirror for case #3 (DELETE the Weaviate row). On rollback
success, the response is "rejected, nothing wrote" and the
caller's retry hits a clean state.

| # | N | W | HTTP | Caller belief        | Retry              | Cleanup obligation                              |
|---|---|---|------|----------------------|--------------------|-------------------------------------------------|
| 2 | S | F | 5xx  | "rejected, retry OK" | yes, idempotent    | DELETE the Neo4j edge before returning 5xx      |
| 3 | F | S | 5xx  | "rejected, retry OK" | yes, idempotent    | DELETE the Weaviate row before returning 5xx    |

**For rollback:**
- Engine O's discovery Cypher needs no state filter. Existence
  IS validity. The standing-guard probes stay simple.
- Recipe v2's two known-good probes (engine_d and engine_e)
  don't need to learn a quarantine state.
- The multi-provider edge collision fix from last night
  (doc-tools a44b9fb) already established that identity =
  `(verb_iri, _tool_urn)`. Rollback by `_tool_urn` is a clean
  DELETE-by-key.
- The dual-store known-good probe — "register fixture → query
  both → both present → done" — is the postcondition test in
  the simplest possible form.

**Against rollback:**
- The rollback CAN fail (Neo4j network blip during the DELETE,
  transaction timeout, APOC unavailability). When rollback
  fails, you've leaked a half-write that *looks routable*: the
  edge or row that did write IS observable, and downstream
  reads cannot tell it from a clean half of a successful
  registration. The failure mode is *silent stale state* until
  someone notices.
- The mitigation — log loudly, alarm on rollback failure, send
  the cleanup task to a dead-letter queue — turns rollback's
  worst case into quarantine-shaped behavior anyway, but with
  no explicit state marker for queries to see.

#### Option B — Quarantine the half-write

On case #2, set a `mesh_registration_state="quarantined"`
property on the Neo4j edge before returning 5xx. Mirror for
case #3 on the Weaviate row. A background reconciler retries
the missing-side write; on success it clears the quarantine
property; on exhausted retries it alarms. Engine O's reads
filter `WHERE r.mesh_registration_state IS NULL OR r.mesh_registration_state <> "quarantined"`.

| # | N | W | HTTP | Caller belief                                      | Retry                | Cleanup obligation                            |
|---|---|---|------|----------------------------------------------------|----------------------|-----------------------------------------------|
| 2 | S | F | 5xx  | "rejected, half-write quarantined for reconciliation" | yes, reconciler-driven | mark Neo4j edge quarantined; reconciler retries W |
| 3 | F | S | 5xx  | "rejected, half-write quarantined for reconciliation" | yes, reconciler-driven | mark Weaviate row quarantined; reconciler retries N |

**For quarantine:**
- *The write actually happened* — quarantine respects that
  truth rather than trying to un-happen it. Operators can
  inspect the quarantined record to see exactly what was
  attempted.
- Quarantine cannot silently leak. The state marker is
  explicit; any query that respects the filter behaves
  correctly; any query that ignores the filter is a bug a
  standing guard can catch.
- The reconciler's "exhausted retries → alarm" path is
  observable, has a runbook, and matches how operators
  already think about partial failures in the rest of the
  system.

**Against quarantine:**
- Every read path that consumes Neo4j / Weaviate needs the
  state filter. Engine O's `_find_compatible_verbs` Cypher,
  `predicate_hybrid_search`, the discovery cache, the
  reconciliation asset's drift query — all add a clause and
  all become a place where the filter could be forgotten.
  Forgotten filter = quarantined verb routes silently.
- The reconciler is new infrastructure (background job,
  retry budget, dead-letter alarm) that doesn't exist yet.
  Building it well takes the same engineering attention as
  building rollback well — but quarantine adds the read-path
  surface area on top.
- The multi-provider edge identity `(verb_iri, _tool_urn)`
  doesn't naturally extend to quarantine — does a quarantined
  edge block a fresh registration for the same `_tool_urn`?
  Does the reconciler MERGE-update or replace? These are
  answerable but each answer is a small contract that has
  to land somewhere.

#### My leaning (not the decision)

Rollback, because:
- Query-side complexity is the cost that compounds across
  Engine O, the SDK, the probes, and the reconciler. Rollback
  has zero query-side complexity; quarantine adds one filter
  to every read.
- Both options have a worst-case mitigation that ends up
  alarming. Rollback's "rollback failed → dead-letter + alarm"
  and quarantine's "reconciler exhausted → alarm" are roughly
  equivalent in operator burden, but rollback's reaches that
  state less often (because rollback is more likely to succeed
  than a multi-minute reconciliation queue is to drain).
- The standing-guard discipline from this arc has been
  "absences should be observable" — Recipe v2's known-good
  probes, the abstention-needs-positive-control rule. Rollback
  fits that shape: a failed registration leaves no trace, and
  a probe failure means "registration didn't happen, fix it,"
  not "registration is in a state we need to interpret."

**The case for the user picking quarantine instead:** if you
expect frequent transient-network blips between the gateway
and Neo4j (real possibility given the cluster's history of
brief Neo4j availability gaps), rollback's worst-case becomes
non-rare, and quarantine's explicit-state failure mode is
strictly better than rollback's silent-leakage failure mode.
This is the call I want you to make.

### Test gate (applies once the fork is resolved)

- The dual-store known-good probe becomes the gateway's own
  postcondition test in CI: register a fixture verb against
  a real Neo4j + Weaviate (testcontainers or sandbox), query
  both stores, assert the verb is present with the expected
  properties, then DELETE the fixture. Same probe used as the
  in-request read-back also runs as a CI guard so a regression
  on either store-write path turns red at PR time, not at
  next-engine-deploy time.
- The Recipe v2 probes in `tests/routing/test_resolve_instance_probes.py`
  stay as they are; they test the routing-side observable, not
  the registration-side. v0.2 must not break them.
- The matrix run (18/18 today) must hold through cutover. If
  it goes red, v0.2 hasn't shipped; if R8 (Engine E as
  provider #2) flips, the gateway has lost the multi-provider
  edge identity invariant.
- A new substrate invariant: every materialized AITool predicate
  edge MUST have non-null `mesh_provider` and a populated
  `mesh_endpoint_url`. This catches the allowlist-drift bug
  class from doc-tools 540fbd5 at the substrate layer, where
  the bug actually lives.

### Cutover — predict-before-run with the masks rule

Per the assignment's Step 3: re-register every existing AITool
through v0.2 and diff the resulting Neo4j edges + Weaviate rows
against what the sensor had materialized.

The masks rule says: *expect at least one discrepancy.* A
dying dual-write path that produces a perfectly clean diff
usually means the diff didn't look where the drift lives, not
that the new path is bug-compatible with the old. The likely
discrepancy candidates, ranked by probability:
- A property the sensor's `_build_relationship_properties`
  allowlist had silently been dropping that the gateway's
  direct-write path will now correctly land (this is the
  full bug class behind doc-tools 540fbd5).
- Edge identity differing on rows where the sensor's old
  `{iri: verb_iri}` match-key collapsed multi-provider
  registrations (now fixed in a44b9fb but with collateral
  data in the existing Neo4j store).
- Stale `provider` / `timeout_s` values on rows materialized
  before this week.
- Weaviate `Predicate` rows whose deterministic UUID was
  computed against an older `(verb_iri, input_uri)` shape.

If the diff comes back clean, that's a verification failure to
investigate, not a victory. Specifically: re-run the diff
querying for the properties listed above by name (the masks
rule's "make sure you looked where the bugs live"). If
*explicit* property-by-property diff also comes back clean,
*then* it's a victory.

### Scope guardrails (hard limits)

- AITool registrations only. The Dataset HAS_DATA pipeline is
  out of scope. The HITL approval flow is out of scope. The
  reconciliation asset is out of scope (still deferred per
  the original ADR-0006 §"Reconciliation asset (deferred to
  follow-up)").
- No changes to Engine O's read paths. No changes to `/resolve`
  or any routing leg. No changes to the BAML schemas or the
  Recipe v2 decision table. v0.2 is registration-path only.
- No work on the docs phase pipeline, Wave-3, or the combined
  ClassifyRoute optimization. Those are the prize this
  amendment unblocks; they are not what this amendment is.

### Indicators for revisiting

- *Gateway becomes the SPOF for a wider class of registrations
  than AITools.* If the Dataset team wants the same atomicity
  guarantees, the gateway path generalizes; the amendment's
  "AITool-only" guardrail relaxes.
- *Quarantine pressure mounts even under rollback.* If
  rollback-fails-and-dead-letters accumulates at a non-rare
  rate, the rollback choice was wrong for this deploy and
  quarantine becomes the right migration.
- *The reconciliation asset starts seeing real drift.* The
  amendment moves a class of drift from "expected daily" to
  "should never happen by construction"; if drift returns,
  something downstream of the gateway is writing without
  going through it. That's an ADR-0006 violation worth
  investigating.
