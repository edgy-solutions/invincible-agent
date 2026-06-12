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

**Status:** Accepted
**Date:** 2026-06-12 (proposed) → 2026-06-13 (accepted with the
conjunctive-read invariant identified as the deciding fact)
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

### Decision — rollback via Restate saga, bounded forward-retry first

**Decided 2026-06-13 by the user, after surfacing the conjunctive-read
invariant that earlier analysis (and the first draft of this
addendum) had missed.** The decision rests on a routing-layer fact
that resolves what looked like a distributed-systems tradeoff. Naming
the invariant is part of the decision — without it, this fork would
genuinely have been balanced; with it, rollback wins outright and
quarantine's strongest surviving argument collapses.

#### The load-bearing safety fact — the conjunctive-read invariant

**In this system, a half-registered verb is already unroutable by
construction.** The dispatch path consumes Neo4j AND Weaviate
*conjunctively* — not as alternatives but as inputs that must agree
before a verb enters the candidate enum the LLM is allowed to pick
from. Per ADR-0018's addendum, `/classify_predicate` builds its
constrained enum from **Weaviate hybrid candidates filtered by the
compat whitelist that Cypher (Neo4j) produced**. Both stores must
register the verb for it to reach the LLM at all.

Walking through cases #2 and #3 of the matrix above with this
property in hand:

- **Case #2 (`N=S, W=F`):** Cypher's compat walk finds the verb
  (Neo4j wrote). But Weaviate's hybrid search doesn't return it (no
  row). The compat-filtered intersection of "Cypher candidates" ∩
  "Weaviate candidates" excludes it. **The LLM literally cannot
  pick it.** The verb is silently unrouted — same observable state
  as "this verb isn't registered yet." Truthful, safe.

- **Case #3 (`N=F, W=S`):** Weaviate's hybrid search finds the
  verb. But Cypher's compat walk returns the empty set (or returns
  it without this verb), so the verb isn't in the compat whitelist
  passed to `/classify_predicate`. The Weaviate hit is filtered out
  before the enum is built. **Same outcome.** Unrouted, safe.

The two escape hatches that would have made single-store presence
sufficient to dispatch are both gone, closed by this very soundness
arc:

- **N=1 Cypher-decisive shortcut** removed by ADR-0019 Contract A
  (`/classify_predicate` no longer returns a candidate just because
  it's the only one in Neo4j; the LLM still has to validate fit).
- **Unconstrained classify on empty compat** removed by the
  Contract B fix two nights ago (dcf9e22) — `/classify_predicate`
  short-circuits to `UNKNOWN` when the subject was resolved and
  compat returned `[]`, instead of falling back to the open
  Weaviate pool.

This means the "observable half-state window" that quarantine was
designed to protect against does not, in fact, expose a routable
verb. **There is no silent leakage to mark.** Quarantine would be
belt added to suspenders that are already load-bearing — and at
the price of a state-filter clause in every read path. That clause
is exactly the bug family this project keeps paying for (allowlist
drift in `_build_relationship_properties`, the temperature override
layer in `init_baml_client`, subClassOf not reaching the LLM enum
before the abba2d2 fix). Adding "every consumer must remember an
implicit check" *manufactures* a new instance of that family.
Rollback adds zero read-side surface.

#### Caveat — one current workaround the invariant requires us to remove

The `/classify_predicate` body at
`agent_fleet/ontology_service/main.py:2152-2164` has a **fabrication
fallback** that synthesizes minimal candidate dicts from the
compat list when the Weaviate intersection comes back empty. Its
comment explicitly identifies what it's working around:

> If the intersection is empty (the subject's compatible verbs aren't
> in Weaviate at all), synthesize candidate dicts directly from the
> supplied IRIs so the LLM still has them — the predicate-registry-
> vs-Weaviate sync gap shouldn't silently swallow a valid route.

This fabrication **breaks the conjunctive-read invariant for case #2**
of the partial-failure matrix (`N=S, W=F`). The verb is in compat
(Cypher returned it), the Weaviate intersection is empty (no row),
the fabrication path fires, and the verb lands in the LLM's enum.
Today the invariant only holds because the sync gap is rare; under
v0.2 it becomes structurally impossible, which removes the
fabrication's reason to exist.

**The fabrication's removal is part of v0.2's scope, sequenced after
cutover.** Order:

1. Restate saga ships (writes Neo4j + Weaviate atomically from any
   reader's perspective once the saga completes).
2. Cutover re-registers every existing verb through the saga,
   refreshing any pre-v0.2 edges that lost their Weaviate row in
   the sensor's allowlist-drift / run-key dedup history.
3. Conjunctive-read invariant test added to CI.
4. Fabrication fallback removed in the same commit as #3 — the test
   is the property; the removal makes the property true; landing
   them together prevents a window where one exists without the
   other.
5. Matrix run gates: still 18/18.

Until this sequence completes, the rollback decision's safety
argument *depends on the saga + the removal landing together*. A
v0.2 implementation that ships the saga without removing the
fabrication leaves the invariant unenforced — same risk as if the
invariant had never been named. The §Test gate item below pins this
in CI; the §Indicators-for-revisiting "single-store sufficient to
dispatch" trigger covers any future re-introduction.

#### Caveat — router-support predicates sit outside the invariant

The conjunctive property holds for **user-question verbs**, which
route through both `/find_compatible_verbs` and `/classify_predicate`
on every request. **Router-support predicates** —
`mesh:resolveInstance` is the first; future ones will be discovered
the same way — are read by Cypher *alone* in
`_discover_instance_resolvers`. A half-write here (case #2: Neo4j
wrote, Weaviate didn't) IS active: the provider gets discovered, the
fan-out happens, the candidates flow back. The Weaviate row is
inert for that predicate class.

Traced: it's currently benign. A half-write resolveInstance edge
points at a real running provider (because the engine's lifespan
registration succeeded enough to emit the MCP), the provider
responds correctly, the decision table consumes its candidates.
The Weaviate row would never have been used anyway because
`/classify_predicate` isn't called for router-support predicates.

But the conjunctive property is itself an *implicit invariant a
future read path could break*. Someone someday builds a consumer
that routes off Neo4j alone for a user-question verb. The day that
ships, rollback's safety argument silently weakens. So the
invariant is **named, written into this amendment as the
load-bearing safety fact, guarded by a standing test (see Test
gate §below), and listed as a revisit trigger (§Indicators)**: if
any future change makes single-store presence sufficient to
dispatch a user-question verb, this rollback decision reopens.

That converts the caveat from a lurking assumption into a tripwire
— the house pattern, applied to the property the architecture
already depends on.

#### Implementation — Restate saga with bounded forward-retry, compensate on exhaustion

The registration handler is a Restate **durable workflow keyed as a
virtual object on `(verb_iri, _tool_urn)`** — the registration
identity that doc-tools a44b9fb established as the
multi-provider-distinguishing key. Restate's virtual-object
semantics serialize concurrent or duplicate registrations for the
same identity behind each other natively, which *is* the answer
to "what happens when a fresh registration arrives mid-failure"
that quarantine had to invent a contract for.

```
WorkflowRegisterAITool(manifest):
  yield ctx.run("contract_d_check",     check_d(manifest))
  yield ctx.run("merge_neo4j_edge",     merge_n(manifest))   # N
  yield ctx.run("upsert_weaviate_row",  upsert_w(manifest))  # W
  yield ctx.run("read_back_probe",      probe_both(manifest))
  return 200 OK
on_step_failure(step, exc):
  # Restate's NATIVE first response: bounded forward-retry within
  # the request budget (~10-15s). This handles the cluster's
  # actual failure profile — transient blips. Retry absorbs a
  # blip invisibly; the caller sees a 3s registration instead
  # of an instant one, and never sees the half-state (which was
  # unroutable by the conjunctive invariant anyway).
  retry_with_backoff(budget=REGISTER_BUDGET_S)
on_retries_exhausted():
  # Only sustained outage reaches here. Saga compensates:
  # durably DELETE whatever wrote, in reverse order. Restate
  # guarantees the compensation runs to completion — which
  # deletes rollback's old worst case ("rollback itself fails
  # and leaks") cleanly.
  yield ctx.run("compensate_weaviate", delete_w_if_written(manifest))
  yield ctx.run("compensate_neo4j",    delete_n_if_written(manifest))
  return 5xx
```

In practice this means:

- **Transient blip → absorbed.** Forward retry completes within
  ~3-15s. Caller sees a slightly slow 200. The half-state never
  becomes externally visible, and even if a read happened during
  the window it would have been unroutable by the conjunctive
  property.
- **Sustained outage → honest 5xx against clean state.** The
  compensation step durably runs. Caller retries against an empty
  substrate. No half-state remains; no quarantine record to
  reconcile.

This is the version of rollback that *bare* rollback couldn't be,
because Restate's durability replaces the "rollback itself can fail"
failure mode. It's also the option Restate makes naturally cheap:
forward retry is Restate's native mode; the compensation step is one
explicit saga branch, not a separate reconciler service.

The matrix's cases #2 and #3 collapse:

| # | N | W | HTTP | Caller belief | Retry semantics | Cleanup obligation |
|---|---|---|------|---------------|-----------------|--------------------|
| 1 | S | S | 200 | "registered" | n/a | none |
| 2 | S | F | 200 *(after forward-retry)* OR 5xx | "registered" or "rejected, clean retry" | Restate forward-retry on W, then saga compensation | Restate-managed: DELETE N durably on exhaustion |
| 3 | F | S | 200 *(after forward-retry)* OR 5xx | "registered" or "rejected, clean retry" | Restate forward-retry on N, then saga compensation | Restate-managed: DELETE W durably on exhaustion |
| 4 | F | F | 5xx | "rejected, no writes landed" | yes, idempotent at handler-entry | none |

#### Concurrency contract — virtual-object keying

Restate virtual objects are single-threaded per key. By keying the
workflow on `(verb_iri, _tool_urn)`, the gateway gets these
properties without writing them:

- **A second registration for the same identity** while the first
  is mid-retry queues behind it. It does NOT race the first into
  the substrate. No double-write, no interleaved partial states.
- **A fresh registration arriving mid-compensation** waits for
  the compensation to complete before starting. The substrate is
  empty when it begins. No "did the previous quarantine block
  this?" contract to invent.
- **Idempotency at handler entry.** Restate's exactly-once
  semantics for side effects mean a replayed handler doesn't
  re-execute `merge_neo4j` if the journal shows it already
  completed.

This is what quarantine had to manually contract for ("does a
quarantined edge block a fresh registration?" — answerable, but
each answer a small contract). Restate's virtual-object model
answers it by construction.

#### SDK side — `register_engine_to_mesh` retry/alarm semantics

The engine-side helper (`agent_fleet/utils/mesh_registration.py`)
gets matched semantics:

- On 5xx from the gateway: retry with backoff a few times within
  the lifespan startup budget.
- On exhausted retries: **log loudly** with the manifest fields
  and the gateway's reason, then **return** — the engine continues
  running unregistered. ADR-0006 §Consequences "Neo4j outages do
  affect runtime routing" applies: the engine serves requests it
  can serve; routing to its verbs simply doesn't happen until a
  successful re-registration on next deploy or manual probe.
- The existing probe discipline (`tests/routing/test_resolve_instance_probes.py`)
  catches "engine up but unregistered" as a named, runbook'd alarm
  — exactly the shape the abstention-needs-positive-control rule
  was promoted to a permanent tripwire for. A future "engine
  starts but never registers" doesn't masquerade as a routing
  bug; the probe fails with the right name on it.

The verb simply won't route in the meantime, which the conjunctive
invariant makes safe — same as before. The system already protects
this; we're just naming and guarding it.

#### The meta-point worth saying

This fork looked like a distributed-systems tradeoff (rollback vs.
quarantine for partial substrate failure) and was actually resolved
by a **routing-layer fact** — the conjunctive read property that the
enum-whitelist work (ADR-0018 addendum) and the Contract B fix
(dcf9e22) had already established. The safety came from work already
done; we just had to name the invariant.

This is the second time in a month the right answer was *"the system
already protects this; name the invariant and guard it"* rather than
*"build the protective state."* The first was Recipe v2 / Gate 6,
where the architecture's discovery-via-registry property meant
Engine E's join required zero Engine O changes (acceptance test
passed by structure, not by code). The pattern is worth naming:
**before designing protective state, check whether the system's
existing invariants already protect against the failure mode — and
if they do, the work is to elevate the invariant to a guarded
named property rather than build the protective state.**

### Test gate

- **Conjunctive-read invariant guard** (load-bearing — the safety
  argument depends on it). Insert a Neo4j-only edge for a fixture
  verb (no Weaviate row). Call `/find_compatible_verbs` for that
  verb's subject + call `/classify_predicate` with the resulting
  compat list. Assert the LLM did NOT receive the verb in its
  constrained enum — the compat-filtered Weaviate intersection
  excluded it. Mirror for the Weaviate-only case (compat-walk
  doesn't include it, so the Weaviate hit is filtered out before
  enum construction). This guard pins the property the rollback
  decision depends on; any future change that makes single-store
  presence sufficient to dispatch a user-question verb turns this
  red BEFORE quarantine becomes the right answer. (Router-support
  predicates like `mesh:resolveInstance` sit outside the
  invariant by design — see Caveat above; their substrate guard
  is the multi-provider edge test that already exists in
  `test_substrate_invariants.py::test_mesh_resolve_instance_has_one_edge_per_provider`.)

- **Gateway saga postcondition test in CI.** Register a fixture
  verb through the v0.2 Restate workflow against a real Neo4j +
  Weaviate (testcontainers or sandbox), assert both stores have
  the expected row with all properties (provider, timeout_s,
  endpoint_url, mesh_*), then DELETE the fixture. Same probe
  shape as the in-request read-back, also runs as a CI guard so a
  regression on either store-write path turns red at PR time, not
  at next-engine-deploy time.

- **Compensation-runs-to-completion test.** Inject a Weaviate
  failure mid-saga, force exhausted retries, assert the Neo4j
  edge is gone after the 5xx returns. Mirror for the inverse.
  This guards the property that makes Restate's durability
  load-bearing for rollback's old worst case.

- **Concurrency contract test.** Two concurrent registrations
  for the same `(verb_iri, _tool_urn)` serialize cleanly via
  Restate's virtual-object key — no double-write, no interleaved
  partial states. A registration arriving while a compensation
  is in flight waits for the compensation to complete.

- The Recipe v2 probes in `tests/routing/test_resolve_instance_probes.py`
  stay as they are; they test the routing-side observable, not
  the registration-side. v0.2 must not break them.

- The matrix run (18/18 today) must hold through cutover. If
  it goes red, v0.2 hasn't shipped; if R8 (Engine E as
  provider #2) flips, the gateway has lost the multi-provider
  edge identity invariant.

- The substrate invariants in `tests/routing/test_substrate_invariants.py::test_mesh_resolve_instance_has_one_edge_per_provider`
  (added in ce599d0) stay as they are. v0.2's writes must satisfy
  them: non-null `mesh_provider`, positive `timeout_s`,
  populated `endpoint_url`, populated `_tool_urn`. This catches
  the allowlist-drift bug class at the substrate layer where the
  bug actually lives — and v0.2 lifts the allowlist hop out of
  the path entirely by writing the substrate directly.

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

- ***Any future change makes single-store presence sufficient to
  dispatch a user-question verb.*** This is the load-bearing
  revisit trigger. The rollback decision rests on the conjunctive-
  read invariant — the LLM only sees verbs that are in both
  Neo4j AND Weaviate. If a future Engine O endpoint, a refactored
  `/classify_predicate`, or a new dispatch path consumes only one
  store, rollback's safety argument silently weakens and
  quarantine moves back onto the table. The standing-guard test
  in §Test gate catches this if it ships; this entry is the
  human-readable backstop saying "if the guard turns red, this
  amendment is being violated, not just a test."
- *Gateway becomes the SPOF for a wider class of registrations
  than AITools.* If the Dataset team wants the same atomicity
  guarantees, the gateway path generalizes; the amendment's
  "AITool-only" guardrail relaxes.
- *Restate forward-retry is exhausted at non-rare frequency.* If
  saga compensations are running more than a handful per month,
  the cluster's transient-blip floor is higher than the
  registration budget assumes. Three responses are then in
  scope: raise the budget, fix the underlying blip cause, or
  reconsider whether forward-retry's "absorb the blip silently"
  is still desirable.
- *The reconciliation asset starts seeing real drift.* The
  amendment moves a class of drift from "expected daily" to
  "should never happen by construction"; if drift returns,
  something downstream of the gateway is writing without
  going through it. That's an ADR-0006 violation worth
  investigating.
