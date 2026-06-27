---
status: Plan (awaiting architect review with second-agent challenge)
date: 2026-06-27
authors: claude (plan-only session)
gates: ADR-0023 (read side) + ADR-0024 Part B (publish backend dependency)
---

# Projector build plan — Neo4j → Postgres → Electric

## 1. Goal

This plan covers the Neo4j → Postgres → Electric projector seam that ADR-0023 names in its "Open questions for the implementing PR" section. The projector is a real component, not a phrase. Landing it unblocks two threads simultaneously: (a) ADR-0024 Part B's publish backend (which cannot start until the projector exists, per the ADR's explicit sequencing note), and (b) the Phase 1 "Monday handoff" runtime-contract check (URN appearing in `subtask_routing_decision` materialization + Sources card populated end-to-end against a real backend rather than the current SSE mock).

This plan describes **what to build, in what order, with what acceptance probes, and what discipline holds across all three hops**. It states four premise-shift decisions explicitly so the architect can challenge each on review. It does NOT cover the publish backend itself, click-to-recall, ADR-0024 Part A's standards integrations, or any UI metaphor decisions about how artifacts arrange themselves in a workspace.

This session ends when this plan is committed. The build session is the next thread, gated on architect review.

## 2. Audit findings

### 2.1 cortex-ui state (the read-side contract that must not change)

- `c:/Users/cnogr/git/cortex-ui/src/api/types.ts` — `Artifact` interface (lines ~243–410) is the Phase 1 contract. Includes `valid_as_of` (required), optional `valid_until`, dual-persona (`produced_by` answerer-side, `produced_for` user-side with nullable persona/entitlements per `[[pingsso-claim-gap]]`), `status: "pending" | "complete" | "failed"`, `resolved_intent`, `rendered_output`, `routing` (full `RouteDecision`), `sources: Source[]`, `graph_trace: GraphTraceNode[]`, `derived_from_artifact_id` (nullable, capture-or-lose-forever).
- `c:/Users/cnogr/git/cortex-ui/src/store/useCanvasStore.ts` — collection store (`artifacts: Artifact[]`, `currentArtifactId`), with `createPendingArtifact` (append) + `updateArtifact` (in-place patch). Stable empty constants (`EMPTY_SOURCES`, `EMPTY_GRAPH_TRACE`) hoisted to defeat zustand reference-inequality loops. Derived selectors: `useCurrentArtifact`, `useCurrentRouting`, `useCurrentSources`, `useCurrentGraphTrace` — these ARE the read shape the projector has to feed.
- `c:/Users/cnogr/git/cortex-ui/src/hooks/useInterviewAgent.ts` — the current source-of-truth path. SSE events from cortex-bff drive `updateArtifact` for each typed event (`route_decision` → routing, `sources` → sources, `graph_trace` → graph_trace, `ui_payload`/`final_payload` → rendered_output + status complete, `pipeline_error` → status failed). **This is the mock-fed path the projector replaces.** When the projector lands, `useInterviewAgent` either becomes a thin event router that the Electric subscription supersedes, or — preferred — Electric writes drive the store and `useInterviewAgent` stops being the truth-path entirely.

### 2.2 Sandbox state (kubectl get pods/services, no exec'ing)

Running pods in `sandbox` namespace include `iagent-neo4j-0` (1/1 Running, 7d13h), `iagent-postgresql-0` (1/1 Running, 7d13h), `iagent-cortex-bff-7468b75848-msrhg`, `iagent-cortex-ui-85bcf77bc5-4zbbm`, `iagent-dagster-daemon`, `iagent-dagster-webserver`, `iagent-dagster-user-code`, plus the engine fleet (A, D, E, F, O, W, data-analyst), mesh-registrar, central-gateway, dag-tools, pub-tools, fuseki, weaviate, redpanda, opensearch.

Services with stable cluster DNS:
- `iagent-neo4j` ClusterIP `10.43.101.11`, ports `7474/TCP` (HTTP) + `7687/TCP` (bolt)
- `iagent-postgresql` ClusterIP `10.43.35.191`, port `5432/TCP`
- `iagent-cortex-bff` ClusterIP, port `8090/TCP`

Image versions (from `kubectl get pod -o jsonpath` on pod images, NOT exec):
- **Neo4j: `neo4j:5.26.0`** — community edition by default image tag, **plugins enabled: `["apoc", "n10s"]`** (per `templates/infrastructure.yaml` lines 106–107). **No CDC plugin configured.** This is the load-bearing version fact for Decision #1.
- **Postgres: `postgres:16`** — confirms wal_level decisions are possible; logical replication slots available out of box.

**Electric is NOT running.** No `electric` pod, no service, no helm template. No references to `electric` / `electric-sql` in invincible-agent source (only ADR mentions). One reference in `cortex-ui/llms.txt` (documentation, not code). The Electric layer has to be added to the chart.

### 2.3 Helm chart patterns

- `templates/infrastructure.yaml` — bare-metal StatefulSet pattern for Neo4j, Postgres, Weaviate, Fuseki. Single-replica, PVC-backed, no Helm subcharts. This is the pattern the projector's Postgres consumer + Electric server would extend, OR the projector could land as a Deployment (not StatefulSet — it's stateless).
- `templates/frontend.yaml` — cortex-ui + cortex-bff Deployments with env-injection from values, optional `tlsTrust.secretName` mount (per `[[cortex-bff-stale-drift]]`). The projector-as-new-Deployment template would mirror cortex-bff's shape.
- `templates/user-deployments.yaml` — the sidecar-registry pattern (per `[[sidecar-registry-pattern]]`). Generic template: each entry in `.Values.userDeployments` renders a Dagster code-location Deployment + a broker Deployment from the same image. The projector does NOT fit this pattern — it's not a user-deployment and not a Dagster code-location. It's an infra-tier component. The `templates/frontend.yaml` pattern is the right ancestor.
- Service naming convention: `{{ .Release.Name }}-{component}` (e.g., `iagent-cortex-bff`). Projector service would be `iagent-projector` (or whatever name Decision #4 settles on).

### 2.4 Existing Neo4j writers

Audit across `c:/Users/cnogr/git/invincible-agent/` for who currently writes AnswerArtifact-shaped things to Neo4j: **nobody.**

- `src/iagent/gateway.py` line 99 instantiates a Neo4j driver, but the only usage at line 1908 is a READ (`/node_details/{node_id}` proxy for the NodeInspector). No writes.
- The other 20 files matching `neo4j_driver|GraphDatabase.driver` are ontology-substrate writers (subject classes, verb edges, ROUTING decisions for ontology layer, S1000D ingest, DMC ingest). None write `AnswerArtifact`.
- Search for `AnswerArtifact`, `answer_artifact`, `valid_as_of` across the repo returns only the two ADRs and the ADR README.
- The current SSE-driven flow assembles a routing+sources+graph_trace+rendered_output bundle in cortex-bff and emits it as typed SSE events. Nothing persists the assembled artifact node.

**Consequence:** Hop 1 must include the **write-side** of the AnswerArtifact, not just the projection. There is no existing graph-native AnswerArtifact to project. The projector building plan is implicitly a three-layer build, not a two-layer one (write-path → projection → read-path), and the write-path is its own pre-requisite scope.

### 2.5 Existing materializations (the Monday-handoff anchor)

`src/iagent/defs/dynamic_supervisor.py` line 765 emits an `AssetMaterialization` with `asset_key=["subtask_routing_decision"]` carrying `subject_uri`, `subject_confidence`, `verb_iri`, `verb_confidence`, `classify_called`, `candidate_count`, `handler_provider`, `handler_endpoint`, `owner_persona`, `output_uri`. This is the Dagster-side substrate the Monday-handoff runtime-contract check observes. The projector's hop-3 completion is the first end-to-end proof that this materialization's URN reaches a Sources card on a real client.

## 3. The four premise-shift decisions

These are the four open questions ADR-0023's "Open questions for the implementing PR" section enumerates. Each is stated explicitly: chosen option, reasoning, rejection-trigger. The architect's second-agent review will challenge these; they are top-down readable and individually rejectable without re-reading the rest of this document.

### Decision 1 — CDC vs polling for Neo4j → projector

**Choice: short-interval polling against Neo4j with an `updated_at`-driven cursor, NOT Neo4j CDC.**

**Reasoning:**

- The deployed Neo4j is `neo4j:5.26.0` — the image tag and the `NEO4J_PLUGINS: '["apoc", "n10s"]'` config strongly suggest **community edition**. **Neo4j CDC (Change Data Capture) is an Enterprise-edition feature.** Adopting CDC means swapping the deployed image to `neo4j:5.26.0-enterprise` AND accepting Neo4j Enterprise licensing terms. That is a premise-shift outside the projector's scope and is the kind of substrate change the audit calls out as a HALT condition.
- Transaction-log tailing requires Neo4j Enterprise's `dbms.tx_log` access patterns and is also outside community-edition surface area. Same blocker.
- Polling is universally available on community edition. The query shape is bounded: `MATCH (a:AnswerArtifact) WHERE a.updated_at > $cursor RETURN a, [(a)-[r]->(t) | {type: type(r), props: properties(r), target_id: t.id, target_labels: labels(t)}] AS edges ORDER BY a.updated_at LIMIT $batch_size`. With `updated_at` indexed, this is O(batch_size) per poll regardless of total artifact count.
- Latency budget for canvas responsiveness: the create-pending → update-complete UX expects the pending artifact to appear instantly (client-side write), then the complete state to arrive within ~1–3 seconds of pipeline finish. A 500ms poll interval gives a P50 round-trip from Neo4j-commit to Postgres-projected of ~750ms (worst-case ~1s). That's inside the budget. Adjustable downward if needed.
- Failure semantics: poll is at-least-once with an idempotent upsert (MERGE-shape on the Postgres side, keyed by `artifact_id`). Restart-safe: cursor persisted in the projector's state table. The cursor is conservative — on restart, replay the last polled window to avoid losing a write that arrived after the cursor was advanced but before commit.
- Operational cost: a polling projector is a single goroutine/coroutine with a simple state loop. The CDC consumer alternative is a Kafka-style consumer with offset management, a separate dependency on the Neo4j CDC plugin and its emitter topic, plus the Enterprise license. Polling is cheaper to operate by ~one full plugin's worth of complexity.

**Rejection trigger:** If the architect rules Neo4j Enterprise is acceptable (either because licensing is already cleared or because the bottleneck calculus differs from what this plan assumes), then CDC becomes preferable for two reasons: lower latency (sub-100ms event delivery vs 500ms poll P50), and event-driven semantics make `SUPERSEDES`-style edge changes (ADR-0024 Part B) propagate without polling-window concerns. If the architect rejects polling, swap to Neo4j CDC + a Kafka or Redpanda topic (Redpanda already runs in the sandbox); the projector becomes a Kafka consumer. The Postgres-shape decision (#2) is independent of this rejection.

**Uncertainty flagged:** The community-vs-enterprise edition determination is from indirect evidence (image tag with no `-enterprise` suffix, plugins list, default config). The build session's first step should be a positive confirmation (`CALL dbms.components()` from within the cluster, which the build session has the permission posture to run). If the deployed Neo4j is in fact Enterprise, this decision is up for re-evaluation BEFORE hop-1 starts.

### Decision 2 — Postgres projection shape

**Choice: one wide table per archetype-class, with a `kind` discriminator column AND a small set of typed-JSON sub-columns for substructures.** Specifically: one `answer_artifact_projection` table (the canvas's primary read source), with `kind = 'AnswerArtifact'` discriminating it from the future `PublishedArtifact` rows that ADR-0024 Part B will project into the same table. Substructures (`routing`, `sources`, `graph_trace`, `rendered_output`) live as typed-JSONB columns, NOT as separate join-tables.

**Reasoning:**

- The canvas read shape is `useCurrentArtifact()` returning a fully-populated `Artifact` row — routing + sources + graph_trace + rendered_output assembled together. A read-path that hits one row (no joins) matches the selector shape directly. JSONB is the right primitive for fields the projector has already denormalized.
- ADR-0024 Part B introduces `PublishedArtifact` as a separate archetype that gets projected to the same read-side. **One table per archetype** (the ADR-listed first option) would mean a `published_artifact_projection` table AND consumer code that knows to query either table per context. **One wide table with discriminator** (the chosen option) lets the canvas read-path treat both archetypes uniformly when shared selectors apply (e.g., "all artifacts authored by this user") and discriminate when they differ. The trajectory matches: when Part B lands, the projector emits rows with `kind = 'PublishedArtifact'` into the same projection table; the read shape grows columns nullable for the kind they don't apply to.
- JSON-payload-with-typed-headers (option 3 in the ADR) is rejected as the primary shape because it puts ALL non-key fields in one JSON blob — which collapses queryability of typed fields (`valid_as_of`, `status`, `produced_for.user_id`) into JSON-path expressions. Those fields are queried by name often enough to be top-level columns. The sub-structures (`routing`, `sources`, `graph_trace`) are JSONB because they ARE assembled blobs from the Neo4j side and don't need per-field queryability at the canvas read layer.
- Schema migration cost when new edge types land: the four standards edges (ADR-0023's reserved vocabulary, ADR-0024 Part A) instantiate per-demand. When `PRODUCED_BY_PROCESS` lands, the projector either (a) folds the BPMN process URN into a nullable top-level column, or (b) extends the `routing` JSONB to carry it. Either is a migration the projector PR ships; neither requires re-shaping the table.
- The Electric Shape API works naturally on a single table with a `WHERE` filter (Electric's "shape" is essentially `SELECT ... FROM table WHERE condition`). A wide table with a discriminator maps directly to a shape; one-table-per-archetype would mean separate shapes the client has to merge.

**Rejection trigger:** If the architect rules `PublishedArtifact` should be a separate table (because the ADR's "instances vs classes" distinction is load-bearing differently than this plan reads), swap to one-table-per-archetype with shared FK to a small shared `actor` table for the producer/consumer references. The hop-2 acceptance probe shape stays the same; only the schema migration script changes. **Alternative rejection:** if the architect rules JSONB sub-columns are not future-proof enough (because `[[ui-contract-assumed-not-published]]` argues for per-field publication), split `routing`, `sources`, `graph_trace` into related tables; canvas reads then hit a `LEFT JOIN ... LATERAL` shape. Higher query cost, more migrations, but per-field discoverability.

### Decision 3 — Position advertisement

**Choice: a monotonic projector-side sequence number ("projector watermark") that maps every applied Neo4j-side write to a Postgres-side advancing integer. The projector publishes its current watermark via a small `GET /projector/watermark` HTTP endpoint AND writes it as a row in a `projector_watermark` table that Electric also syncs.**

**Reasoning:**

- "See-your-write" latency budget: user types query → cortex-bff writes AnswerArtifact to Neo4j (commit at T0) → projector polls and applies the write to Postgres (T0 + ~500ms P50, ≤ 1s P99) → Electric pushes the updated row to the client (T0 + ~700ms P50) → canvas renders complete. The watermark protects against the client rendering a stale view before the projector caught up. After the cortex-bff write, the client waits until projector_watermark ≥ the write's watermark.
- The watermark is **projector-local monotonic, not a Neo4j tx-id and not a Postgres tx-id.** Both Neo4j and Postgres txn-ids have edge cases (Neo4j tx-ids are not strictly monotonic across rollbacks; Postgres txids wrap). A projector-local sequence is simple, correct-by-construction, and decoupled from substrate quirks. The cost is: the projector is the sequence-of-record, so its restart story has to recover the watermark from the last-committed-row's value (a `SELECT MAX(watermark) FROM answer_artifact_projection` at startup).
- "How the client knows to wait": cortex-bff returns the watermark in the response to the write (the SSE `stream_end` event includes `{watermark: N}`). The client compares N against the Electric-synced `projector_watermark.value` row; when the latter ≥ N, the artifact is guaranteed-visible. Implementation: a small `await until` helper in the cortex-ui SDK that subscribes to the watermark row.
- Why publishing the watermark via Electric-synced row (rather than only via HTTP): Electric is already the streaming-sync transport; folding the watermark into a row removes the second HTTP round-trip from the critical path. The HTTP endpoint stays available for non-Electric consumers (probes, admin tools).
- Why NOT a Neo4j-side Lamport clock: Neo4j doesn't natively expose one, and emulating one in Cypher (incrementing a global counter on every artifact write) creates lock contention that doesn't pay back.

**Rejection trigger:** If the architect rules the watermark should be the Neo4j tx-id instead (because the projector should NOT be the sequence-of-record), the design shifts to: projector copies `tx-id` onto every projected row; client waits-until `projector_max_tx_id ≥ N`. Requires the Neo4j write-path to return its commit tx-id, which is a small wrapper around the existing driver. **Alternative rejection:** if the architect rules Electric's built-in offset / position semantics are sufficient (Electric advertises a position per shape), drop the projector watermark and let the client wait-until-Electric-position. Requires verifying Electric's position semantics match the projector's apply order — which is true for in-order apply but needs the build session to validate.

### Decision 4 — Where the projector runs

**Choice: a new Deployment named `iagent-projector`, deployed via a new helm template `templates/projector.yaml`, mirroring the cortex-bff shape (single replica, env-driven config, no PVC needed — projector state lives in Postgres). It runs as its own process, with its own lifecycle independent of cortex-bff. The Electric server runs alongside as a sibling Deployment (`iagent-electric`) — distinct because Electric has its own lifecycle, exposed port, and image.**

**Reasoning:**

- **Lifecycle independence:** the projector's apply loop should not restart whenever cortex-bff restarts (which happens on every cortex-bff deploy). Conversely, a projector restart should not impact cortex-bff's request path. Co-locating them couples lifecycles in a way that creates outages when none is required.
- **Auth surface:** the projector needs Neo4j credentials (poll-side) AND Postgres credentials (apply-side). Both already exist in the chart (`.Values.neo4j.auth`, `.Values.postgresql.auth`). Mounting them onto a dedicated projector Deployment is one env-config block; mixing them into cortex-bff expands cortex-bff's credential surface for no benefit.
- **Observability seam:** the projector logs go to a labeled pod (`app=iagent-projector`) that is grep-able as a unit. A liveness probe verifies the apply loop is advancing (the watermark increments under load). A readiness probe verifies the Neo4j and Postgres connections are healthy. If the projector is stuck, the sandbox finds out via the readiness probe failing — which it cannot do if the projector is embedded in cortex-bff.
- **Why not a Dagster sensor:** a sensor is one of Dagster's polling primitives, but the projector is not a Dagster asset and shouldn't appear in the Dagster graph. Dagster runs already have their own materialization assets (`subtask_routing_decision`, `subtask_graph_trace`, `subtask_sources`). Adding the projector as a sensor conflates Dagster's role (orchestration of pipeline runs) with the projector's role (CQRS read-side maintenance).
- **Why not a sidecar to Neo4j:** Neo4j runs as a StatefulSet; sidecars to StatefulSet pods complicate the volume/restart story for no operational gain. The projector is network-attached to Neo4j over bolt, same as any other client.
- **Why distinguish projector and Electric server:** Electric is a third-party server with its own release cadence and image. Bundling its lifecycle with the projector means upgrading Electric requires re-rolling the projector and vice versa. Distinct Deployments let each upgrade independently. The two communicate over Postgres (Electric reads from Postgres just like any other consumer).
- **`[[sidecar-registry-pattern]]` does NOT apply here.** That pattern is for self-describing user-deployments that register their domain assets with the central broker. The projector is infrastructure — it is not a user-deployment and it doesn't advertise domain content.

**Rejection trigger:** If the architect rules the projector should be embedded in cortex-bff (because operational simplicity > lifecycle independence at this stage), fold the projector loop into cortex-bff's startup as a background task with its own asyncio task. The probe shapes change (the projector-loop-stuck signal now has to surface through cortex-bff's health endpoint), and a cortex-bff restart triggers a brief catch-up window on the projector watermark. **Alternative rejection:** if the architect rules Electric and the projector should be one binary (because cortex governs both halves of the CQRS pair per ADR-0023), then the projector image bundles a small embedded Electric-like sync — this materially increases project scope and is unlikely; raised only because the ADR explicitly says "cortex governs both halves."

## 4. Hop 1 plan — AnswerArtifact as a real Neo4j node

### Scope

Stand up the write-side. Add code to cortex-bff that, at SSE `stream_end` (or earlier on individual events), commits a real Neo4j AnswerArtifact node with its typed edges. The fields written match the Phase-1 `Artifact` type contract exactly (this is the load-bearing constraint: the Neo4j node's properties + edges have to project cleanly into a row that round-trips into the `Artifact` shape the cortex-ui store consumes).

Specifically:
- `(:AnswerArtifact {id, created_at, updated_at, valid_as_of, valid_until?, question_text, resolved_intent, message_id, status, rendered_output})` — `rendered_output` as inline JSONB property until the size discriminant fires (ADR-0023 leaves this to the implementing PR; this plan ships inline, files a follow-up for the size threshold).
- `(:AnswerArtifact)-[:PRODUCED_BY]->(:Actor {actor_type, actor_id, version?, endpoint?, code_hash?})` — agent identity captured at creation. Refined from the pending-sentinel only if the routing event carries real `handled_by`.
- `(:AnswerArtifact)-[:PRODUCED_FOR]->(:Actor {actor_type, user_id, is_authenticated, user_persona?, entitled_domains?})` — user-side persona slot present even when null (per `[[pingsso-claim-gap]]`).
- `(:AnswerArtifact)-[:DERIVED_FROM]->(:AnswerArtifact)` — when `derived_from_artifact_id` is non-null. (Phase 1 almost always null; the edge-write code path exists for when follow-up detection lands.)
- `(:AnswerArtifact)-[:ROUTED_AS]->(:RoutingDecision {subject_uri, verb_iri, owner_persona, ...})` OR as inline properties on the AnswerArtifact — this hop picks **inline properties** since the first re-use case for a shared RoutingDecision node hasn't fired yet (per ADR-0023's open question). When that case fires, a follow-up migration extracts.
- `(:AnswerArtifact)-[:CITES]->(:Source {uri, type, label})` per source — Source nodes deduped by URN (`MERGE (s:Source {uri: $uri})` semantics), with the per-artifact citation evidence on the `CITES` edge (`{snippet, relevance, open_url}`).

The write is **idempotent** (`MERGE` on `AnswerArtifact.id`), so the pending → complete transition is one Cypher write with property updates, not two creates.

### Probe shape (predict-before-run)

Probe `test_hop1_neo4j_writeback.py` (under `tests/sandbox_e2e/` to mirror existing layout):

```
PRECONDITION: cortex-bff is running, Neo4j is reachable.

GIVEN a known question text "what is engine A's owner_persona for retrieveKnowledge?"
GIVEN a known PRODUCED_FOR actor (test user with stable user_id "test-user-7d")
GIVEN message_id "msg-hop1-001"

WHEN cortex-bff receives the question through its normal entry path
AND the routing decision arrives with verb_iri == "mesh:retrieveKnowledge"
AND stream_end fires

THEN a (:AnswerArtifact {id: <known-id>, valid_as_of: <committed-timestamp>}) node exists in Neo4j.
AND (:AnswerArtifact)-[:PRODUCED_FOR]->(:Actor {user_id: "test-user-7d"}) exists.
AND (:AnswerArtifact)-[:PRODUCED_BY]->(:Actor {actor_type: "agent"}) exists with actor_id != "pending"
    (the routing event refined the sentinel).
AND (:AnswerArtifact)-[:CITES]->(:Source) edges resolve to at least one Source node whose uri is non-empty.
AND the (:AnswerArtifact).valid_as_of property is a real epoch-millis number, NOT null, NOT 0.

ASSERT: a second write with the same id (replay) does NOT create a duplicate node — count of (:AnswerArtifact {id: <known-id>}) == 1.
```

The probe is "predict a specific value AND a specific change-propagation": the predicted value is the question text, the predicted change-propagation is that the pending-sentinel `produced_by.actor_id` got refined to a real engine_name when routing arrived.

**This probe MUST be able to fail.** Failure modes it has to catch:
- The write never happens (cortex-bff has no Neo4j write path) — the node is absent.
- The write happens but `valid_as_of` is null — capture-or-lose-forever violated.
- The write happens but `produced_by.actor_id` is still "pending" — the routing-event refinement path didn't apply.
- The replay creates a duplicate node — idempotency violated.
- The `:Source` node has empty `uri` — `MERGE` keyed on a missing field.

### Red-first sequence

1. **Write the probe first**, against the running sandbox. Run it. **It must fail** — there is no Neo4j write path in cortex-bff today (audit confirms only a `/node_details` reader). The predicted-RED is "no `(:AnswerArtifact {id: <known-id>})` exists." Inspect the failure message; confirm it's the predicted-RED and not e.g. a Neo4j connection error.
2. Add the Neo4j write helper to cortex-bff. Idempotent MERGE patterns. PRODUCED_FOR/PRODUCED_BY/CITES edge writes.
3. Hook the SSE event handlers in cortex-bff to call the write helper at `stream_end` (and on each event for the pending → complete update path — this exercises Hop 2's update probe later).
4. Re-run the probe. Expect GREEN. Inspect: open Neo4j browser, confirm by eye the node + edges shape match the predicted property names.

### Breakpoint

Hop 1 is done when:
- The probe is green AND was red before the implementation landed.
- A second probe variant — re-run the same question with a fresh `id`, then re-run AGAIN with the SAME `id` — shows idempotency (count == 1).
- An inspector check on a real Neo4j browser session confirms the node has `valid_as_of` populated and the edges resolve to the expected target labels.
- The Hop 2 probe (next section) has been WRITTEN but not yet run. The build session is about to open Hop 2.

## 5. Hop 2 plan — the projector, Neo4j → Postgres

### Scope

Stand up the projector: a new `iagent-projector` Deployment (Decision #4), polling Neo4j on a 500ms interval against an `updated_at` cursor (Decision #1), upserting into the `answer_artifact_projection` table on Postgres (Decision #2), and advancing the `projector_watermark` row (Decision #3).

Schema migrations land in this hop:
- `CREATE INDEX ON :AnswerArtifact(updated_at)` on Neo4j (required for poll efficiency).
- `CREATE TABLE answer_artifact_projection (id text PRIMARY KEY, kind text NOT NULL DEFAULT 'AnswerArtifact', created_at bigint, updated_at bigint, valid_as_of bigint NOT NULL, valid_until bigint, question_text text, resolved_intent jsonb, message_id text, status text, rendered_output jsonb, produced_by jsonb, produced_for jsonb, routing jsonb, sources jsonb, graph_trace jsonb, derived_from_artifact_id text, watermark bigint NOT NULL)`.
- `CREATE TABLE projector_watermark (id int PRIMARY KEY DEFAULT 1, value bigint NOT NULL)` — single-row table, the published current watermark.
- `CREATE TABLE projector_cursor (id int PRIMARY KEY DEFAULT 1, last_polled_updated_at bigint NOT NULL)` — projector's own resumable state.

The projector's apply loop: poll Neo4j → assemble the projected row (denormalizing edges into the JSONB columns) → upsert into `answer_artifact_projection` with the next watermark → upsert into `projector_watermark` → advance cursor.

### Probe shape (predict-before-run)

`test_hop2_projector_apply.py`:

```
PRECONDITION: Hop 1 is green. cortex-bff writes AnswerArtifact nodes. iagent-projector is deployed.

PHASE A — insert propagation:
GIVEN a known question text "what is engine A's owner_persona for retrieveKnowledge?"
WHEN cortex-bff completes the full pipeline (driving Hop 1's write)
AND the projector's next apply cycle fires (≤ 1.5s wait)

THEN a row exists in answer_artifact_projection with id == <known-id>
AND the row's valid_as_of MATCHES the Neo4j node's valid_as_of
AND the row's sources::jsonb contains an element whose uri matches Hop 1's recorded Source
AND projector_watermark.value > <pre-write watermark>

PHASE B — update propagation (THE DISCRIMINATING TEST):
GIVEN the projected row from Phase A exists with status == 'complete'
WHEN cortex-bff issues an updateArtifact equivalent that sets status to 'failed' (simulate a stale-mark)
AND the Neo4j AnswerArtifact's status property is set to 'failed' (the write commits)
AND the projector's next apply cycle fires (≤ 1.5s wait)

THEN the row in answer_artifact_projection has status == 'failed'
AND the row's updated_at is greater than its value pre-update
AND projector_watermark.value advanced further

PHASE C — idempotent replay:
GIVEN the Neo4j AnswerArtifact has not changed
WHEN three consecutive polls fire
THEN the row in answer_artifact_projection is unchanged across the three polls (same updated_at, same watermark)
AND projector_watermark.value advances ONLY when a real change applies (NOT on every poll)
```

**Phase B is the load-bearing test.** Insert-only projectors are easy to write; update-respecting projectors are where the rot lives. The probe MUST fail if the projector treats updates as inserts (duplicates), if it ignores updates (stale rows), or if it advances the watermark on every poll regardless of change (Electric clients then see spurious "row changed" events).

### Red-first sequence

1. **Write the probe against a sandbox where Hop 1 is green but no projector exists.** Run it. **Phase A must fail** with "row not found in `answer_artifact_projection`" (the table doesn't even exist, or the projector isn't applying). Predicted-RED. Confirm.
2. Run the schema migrations on Postgres. Deploy the projector (Deployment template added to helm).
3. Re-run Phase A. Expect GREEN.
4. With the projector running, simulate the update in Phase B (deliberately patch the Neo4j node to set `status = 'failed'`). Re-run the probe — Phase B has never run on the new projector. **Predict: GREEN if updates apply; RED if the projector only inserts.** Inspect either outcome carefully. (This is the moment where many projector implementations silently fail — the implementation might have "looked complete" after Phase A passed.)
5. Phase C is a stability check; run after A and B are both green. Predicted GREEN if watermark advancement is change-gated.

### Breakpoint

Hop 2 is done when:
- All three phases are green, and Phases A and B were red before the projector code landed.
- The Hop 3 byte-identical-diff probe (next section) has been WRITTEN but not yet run.
- A short observability check: `kubectl logs deployment/iagent-projector --tail=50` shows the apply loop is alive and advancing the cursor. A stuck loop is the projector's quiet-failure mode; the operator has to be able to see it from logs.

## 6. Hop 3 plan — Postgres → Electric → store

### Scope

Stand up the Electric server (`iagent-electric` Deployment + Service). Configure a single Shape that selects `answer_artifact_projection` rows scoped by the requesting user's `produced_for.user_id` (so the canvas only syncs that user's artifacts — privacy-preserving by construction). Add the Electric client subscription to `cortex-ui` that drives `useCanvasStore` from the synced rows.

Critical constraint: **the `Artifact` type contract in `c:/Users/cnogr/git/cortex-ui/src/api/types.ts` does NOT change.** The Electric-synced row maps 1:1 onto the existing `Artifact` shape. The `useInterviewAgent` mock-fed path either stops being the source of truth (preferred) or remains as a fast-path for the immediate-create-pending step while Electric drives the durable updates (acceptable interim).

### Probe shape

`test_hop3_electric_to_store_diff.py` is a **two-part probe**.

**Part 1 — byte-identical type contract:**

```
GIVEN c:/Users/cnogr/git/cortex-ui/src/api/types.ts as of the commit BEFORE Hop 3 starts (git ref pinned)
WHEN Hop 3's swap lands
THEN git diff between the pre-swap commit and the post-swap commit on src/api/types.ts is EMPTY for the Artifact interface block (lines covering the Artifact interface).

If the diff is non-empty:
  HALT. Surface to the architect for review. The type-contract drift IS a premise-shift requiring its own decision. The build does NOT proceed without architect sign-off on the diff.
```

The Artifact type byte-identical-diff is the load-bearing check that the entire substrate swap is data-shape-preserving. The diff probe is automatable (a script that runs `git show $pre_hop3_ref:src/api/types.ts | grep -A 200 'interface Artifact' > /tmp/pre.ts` and the equivalent on `HEAD`, then diffs them).

**Part 2 — propagation through the full stack:**

```
PRECONDITION: Hop 2 is green. iagent-electric is deployed. cortex-ui subscribes to the Electric Shape.

GIVEN a known question text and a known user_id "test-user-7d"
WHEN cortex-bff completes the pipeline (Hop 1 write → Hop 2 projection)
AND ≤ 2s elapse
THEN useCanvasStore.artifacts contains a row with the predicted id
AND useCurrentArtifact() returns an artifact whose sources[].uri matches the URN that subtask_routing_decision materialized on the Dagster side
AND no SSE event handlers in useInterviewAgent fired for the rendered_output field (the data path is now Electric, not SSE).

UPDATE-propagation:
GIVEN the artifact is in the store with status == 'complete'
WHEN a backend agent updates the Neo4j node (Hop 1's update path) to set status == 'failed' (simulated)
AND ≤ 2s elapse
THEN useCanvasStore.artifacts shows the same id with status == 'failed' WITHOUT a page reload AND WITHOUT a UI code change.
```

The "no SSE handler fired" assertion is what distinguishes "Electric is the path" from "SSE and Electric both wrote, the store happens to look right." Without the assertion, the test passes for the wrong reason (the SSE mock path still drives the store, Electric is silent or duplicated).

### Red-first sequence

1. **Write Part 1's diff probe.** Run it BEFORE any Hop 3 code lands. Pin `pre_hop3_ref = HEAD-on-master-before-hop3`. The probe should be GREEN at this point (the diff of master against itself on `Artifact` is empty). This is a degenerate-green; it becomes meaningful only as Hop 3 progresses.
2. **Write Part 2.** Run it. **Predicted-RED**: the Electric subscription doesn't exist yet, so `useCanvasStore` updates come only from `useInterviewAgent` SSE. The "no SSE handler fired" assertion fails because SSE drives everything. Confirm the RED matches the prediction.
3. Deploy `iagent-electric`. Add the Shape config. Add the cortex-ui client subscription. Update `useInterviewAgent` to stop driving `rendered_output`/`sources`/`graph_trace`/`routing` updates (or stop entirely if the create-pending step can shift to a local-write-then-await-watermark shape).
4. Re-run Part 1's diff probe. **If the diff is non-empty, HALT.** Inspect what changed and surface to architect. If the swap was successful, Artifact-shape should be byte-identical; any non-empty diff is the premise-shift this hop is supposed to NOT introduce.
5. Re-run Part 2. Expect GREEN.

### Breakpoint

Hop 3 is done when:
- Part 1 diff probe is GREEN at the end (after the swap) — the Artifact type didn't drift.
- Part 2 propagation probe is GREEN AND was red before the swap.
- A manual canvas check: type a query in the running cortex-ui, watch the pending → complete transition, watch the Sources card populate with a URN that matches `subtask_routing_decision`'s `subject_uri` in the corresponding Dagster run. This is the Monday-handoff visual proof.
- Optional but recommended: shut down the SSE path entirely for one test session and confirm the canvas still works end-to-end via Electric alone. (If it doesn't, the SSE path is still load-bearing and the swap is incomplete.)

## 7. Cross-cutting discipline

These rules apply across all three hops. Each hop's plan references them above; this section makes them load-bearing in one place.

- **Integration probe per contract, each able to fail.** Per `[[feedback-endpoint-probe-per-engine]]` and `[[feedback-verification-must-fail]]`: every hop's probe predicts a SPECIFIC value AND a SPECIFIC change-propagation. A probe that returns "all green" because the readback cache stayed warm, or because the projected row was the mock all along, is the always-green anti-pattern this stack now codifies as a recognized class. The Phase B "update propagation" assertion in Hop 2's probe is the canonical instance: insert-only projectors look complete until update arrives.

- **Pre-written fixtures must fail first.** Per `[[pre-written-fixtures-must-fail-first]]`: each hop's probe is written BEFORE the hop's code, and is shown FAILING before the hop's code lands. The red-green transition is the proof. Specifically:
  - Hop 1: probe written, predicted-RED is "no AnswerArtifact node in Neo4j" — confirm RED before adding the cortex-bff Neo4j writer.
  - Hop 2: probe written, Phase A predicted-RED is "row not in answer_artifact_projection" — confirm RED before deploying the projector. Phase B's update-propagation must ALSO go red before code, NOT just degenerate-green by accident of the insert path.
  - Hop 3: byte-identical-diff probe is degenerate-green pre-swap; Part 2 must go RED before Electric is deployed.

- **Verify by inspection, not by attestation.** Per `[[verify-subtle-acceptance-by-inspection]]`: when the agent reports a hop green, the architect (or a different reviewer) opens the actual diff and the actual probe output. Specific inspections this plan calls out:
  - Hop 1: open Neo4j browser, see the node + edge shape match the predicted property names. Don't accept "the probe passed" without the visual confirmation.
  - Hop 2: `kubectl logs deployment/iagent-projector` to confirm the apply loop is actually running. A stopped projector with a backfilled-once table looks identical to a healthy projector from the probe's vantage.
  - Hop 3: open the cortex-ui DevTools, inspect the zustand store state across an update, confirm the update arrived via Electric subscription (not via an SSE event handler).

- **Halt on premise-shifts.** Per `[[feedback-baseline-regression-gate]]` and the discipline this plan inherits: if the build hits a substrate-shape that wasn't in the audit (e.g., Neo4j turns out to be Enterprise after all, Postgres has a schema migration the architect didn't bless, cortex-bff's deploy story prevents the projector Deployment from being added), HALT. Surface the premise-shift. Do not silently pick. This plan's audit is the baseline; deviations from it require architect acknowledgment before they get built around.

- **Fixture richness before hardening.** Per `[[fixture-must-exercise-paths]]`: each hop's probe exercises NOT just the happy path. Hop 1's probe exercises both initial-write AND pending-sentinel-refinement AND idempotent-replay. Hop 2's probe exercises insert AND update AND idempotent-poll. Hop 3's probe exercises type-contract-stability AND propagation AND update-without-SSE. The probe suites are richer than "did the row appear"; they exercise the paths the binding contracts care about.

## 8. Monday handoff note

The Monday work-cluster handoff Phase 1 was waiting on has two parts: (a) the URN appears in the `subtask_routing_decision` Dagster materialization (already true on the supervisor side, see audit §2.5 — line 765 in `dynamic_supervisor.py`), and (b) the Sources card in the cortex-ui canvas surfaces the URN end-to-end against a real backend (currently mock-fed via SSE). Hop 3's completion is the first real end-to-end proof of part (b): when a user types a query, the supervisor emits `subtask_routing_decision` with `subject_uri = <URN>`, cortex-bff writes the AnswerArtifact + Sources to Neo4j (Hop 1), the projector lands the row in Postgres including the Sources JSONB (Hop 2), Electric pushes it to the client, and the canvas's Sources card renders the URN (Hop 3). The same projector that gates the publish backend (ADR-0024 Part B) is the substrate the Monday-handoff runtime-contract check depends on. These are the same thread, not adjacent ones.

## 9. What this plan does NOT cover

- **The publish backend (ADR-0024 Part B).** The `PublishedArtifact` node + `PROMOTED_TO` + `SUPERSEDES` edges + the publish action + the DataHub scrub job for orphan detection. All of those depend on this projector but none of them are scoped here. The "future fit" reasoning in Decision #2 (one wide table with discriminator) is the only place this plan touches Part B's eventual shape; the actual Part B work is a separate thread, gated on this plan landing AND a review-and-build on it AND a separate Part B planning thread.
- **Click-to-recall affordance** (per ADR-0024's "Click-to-recall is independent" note). One-line wiring on `Message.artifactId` → `setCurrentArtifact(id)`. Independent of both the projector and the publish substrate. Out of scope here.
- **ADR-0024 Part A standards integrations** — BPMN / CALM / ODPS / ODCS. The reserved edge vocabulary on AnswerArtifact (`PRODUCED_BY_PROCESS`, `CONFORMS_TO`, `IS`, `WITHIN`) is NOT exercised in Hop 1. When the first standard pulls in for integration (per Part A's triggers), it will need its own Neo4j writer + projection treatment — a follow-up to this plan, not part of it.
- **Freshness-computation strategy.** ADR-0023 lists three (static TTL, substrate-change detection, on-read check). This projector captures `valid_as_of` and grounding (CITES + ROUTED_AS) so any of the three works. Picking which one ships first is a separate decision; the projector's job is to make the captured data available.
- **User-Actor population shape under PingSSO claim gap.** The slot exists from day one with explicit-null per `[[pingsso-claim-gap]]`. When claims expand (out of scope here), populating becomes a write-only change; no projector schema migration required.
- **Workspace UI metaphor** — tabs / projects / free-spatial canvas. The collection is durable as of Phase 1; how it arranges in a workspace is a UI-arc decision after Hop 3.
- **Latency budget measurement under load.** ADR-0023's "Consequences" section flags that the write-path now touches Neo4j + projector + Electric, longer than the current "render and forget" shape. Measuring under realistic load is a post-Hop-3 task; this plan's choices argue the budget is sufficient but don't verify it.

## 10. STOP for this thread

**This plan-commit is the STOP point.** Binding.

This thread does NOT:
- Write backend code (no Neo4j writer in cortex-bff, no projector Deployment, no Electric Shape).
- Modify any helm chart (no new templates, no values changes).
- Write to any database (Neo4j read-only via inspector existing today; Postgres untouched).
- Change the cortex-ui Artifact type (zero diff against `src/api/types.ts`).
- Open the build session.

The architect's review of this plan (with a second agent challenging the four decisions specifically) is the next step. The build session is the step after that, gated on architect sign-off on whichever subset of the four decisions survives review.

If, in the moments after this commit, the pull arrives to "just sketch hop 1's Neo4j write while I'm in here" — STOP. The architect's review is the next step; the build is the step after that. Skipping the review collapses the premise-shift surface into the build, which is exactly the discipline-failure the four-decision section is structured to prevent.
