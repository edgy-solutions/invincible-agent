---
status: Plan (revised post-architect-review; build-gated on revisions held in this commit)
date: 2026-06-27
authors: claude (plan-only session, revised after architect's second-agent challenge)
gates: ADR-0023 (read side) + ADR-0024 Part B (publish backend dependency)
revision: 1 — folds in Decision 0 (cortex-bff as write authority), Decision 1 rewritten as poll-as-interim, Decision 3 sent back for Electric-position spike first, build-sequencing updated. Original plan: commit ded7cc7.
---

# Projector build plan — Neo4j → Postgres → Electric

## 1. Goal

This plan covers the Neo4j → Postgres → Electric projector seam that ADR-0023 names in its "Open questions for the implementing PR" section. The projector is a real component, not a phrase. Landing it unblocks two threads simultaneously: (a) ADR-0024 Part B's publish backend (which cannot start until the projector exists, per the ADR's explicit sequencing note), and (b) the Phase 1 "Monday handoff" runtime-contract check (URN appearing in `subtask_routing_decision` materialization + Sources card populated end-to-end against a real backend rather than the current SSE mock).

This plan describes **what to build, in what order, with what acceptance probes, and what discipline holds across all three hops**. It states five premise-shift decisions explicitly (Decision 0 elevated post-review, plus the original four) so the architect can challenge each on review. It does NOT cover the publish backend itself, click-to-recall, ADR-0024 Part A's standards integrations, or any UI metaphor decisions about how artifacts arrange themselves in a workspace.

**Two of the five decisions are interim-with-named-successor.** Decisions 1 and 3 are explicitly labeled as throwaway scaffolding pointing at a single shared successor (cortex-bff → Restate handler → Redpanda topic → projector consumes topic). The coupling is load-bearing — see Decision 3's revision and the new "Through-line — interim vs successor" section.

This session ends when this revised plan is committed. The build session is the next thread, gated on architect sign-off on the revision.

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

## 3. The five premise-shift decisions

The original draft had four — the four open questions ADR-0023's "Open questions for the implementing PR" section enumerates. The architect's second-agent review elevated a fifth (Decision 0) that the original plan buried in §2.4 as an audit consequence. Each decision is stated explicitly: chosen option, reasoning, rejection-trigger. Decisions are top-down readable and individually rejectable without re-reading the rest of this document.

**Two interim/successor pairs are flagged.** Decisions 1 and 3 are explicitly coupled (per `[[coupled-interim-mechanisms-retire-together]]` — this plan is the first banked instance of that rule). They retire together under the same successor named in §3.5's "Through-line — interim vs successor" section.

### Decision 0 — cortex-bff as the AnswerArtifact write authority

**Choice: yes — cortex-bff becomes the direct AnswerArtifact write authority to Neo4j as the Hop 1 deliverable. Acknowledged as an architectural change to cortex-bff's role, not a projection of existing data. Conscious yes, not a rider on the projector approval.** Conscious "via Restate later" footnote: when the Restate path lands (per the Through-line in §3.5), cortex-bff stops being the *direct* writer and becomes the *invoker* of a durable Restate handler that owns the persistence. The footnote is load-bearing — it prevents future readers from treating "cortex-bff writes Neo4j" as a permanent invariant of the system.

**Reasoning:**

- The audit (§2.4) confirmed: **no component in invincible-agent currently writes AnswerArtifact-shaped objects to Neo4j.** `src/iagent/gateway.py` line 1908 reads Neo4j for the inspector panel; it does not write. The 20 other files matching `neo4j_driver|GraphDatabase.driver` write ontology-substrate content (subjects, verbs, ROUTING decisions for the ontology layer), not artifacts. The SSE bundle that cortex-bff assembles today is **transient** — it goes out the SSE socket and is lost as soon as the client tab closes. This is the absence of durability the projector plan is named for, and it is the largest single fact in the whole plan.
- cortex-bff is the natural writer because it is **already where the bundle is assembled** — routing decision, sources, graph trace, rendered output all flow through cortex-bff before they are emitted as SSE events to the client. The work of "make this a graph node" is one Cypher write away from work cortex-bff already does. Putting the writer anywhere else (a new service, a sidecar, embedded in an engine) would require teaching that consumer how to receive the assembled bundle.
- This expands cortex-bff's responsibility surface in a material way: it gains write-credentials to Neo4j, gains responsibility for capture-or-lose-forever fields (`valid_as_of`, `produced_for`, `produced_by`, `derived_from_artifact_id`), and gains a new failure mode where a Neo4j outage means user-visible artifacts are lost even if the rest of the pipeline succeeded. The "trailing-steps-nonfatal" discipline (`[[feedback-trailing-steps-nonfatal]]`) applies — the Neo4j write must not break delivery of the SSE bundle to the user; it has to either succeed durably or fail visibly without taking the user's answer down.
- **Why this is a conscious yes and not a rider on Decision 4:** Decision 4 chooses *where* the projector runs. Decision 0 chooses *who writes the source-of-truth*. Those are different decisions. The projector consumes whatever the write-authority produces; the write-authority doesn't have to be cortex-bff in principle (an engine could write directly, or a future Restate handler could). Treating Decision 0 as automatic conflates two architectural choices and skips the architect's chance to challenge the "cortex-bff gains a major new responsibility" framing.

**Via-Restate-later footnote:** The cortex-bff direct-write is **interim, coupled to Decisions 1 and 3**. When Redpanda becomes load-bearing for cortex-bff for independent reasons (the streaming-ingest path that's coming for other reasons), the AnswerArtifact write moves *behind* a Restate handler. The handler owns: step-1 Neo4j write, step-2 Redpanda emit, both journaled. cortex-bff shrinks from "writer" to "invoker of the durable handler." This is NOT a distributed transaction across Neo4j+Redpanda (2PC is overkill); it's durable execution — if the handler crashes between Neo4j write and topic emit, Restate resumes from the journal and drives the unfinished step exactly once. This is openddil's pattern with Neo4j added as a second target inside the durable handler — a pattern the platform already runs and trusts. See §3.5 Through-line.

**Rejection trigger:** If the architect rules cortex-bff is the wrong authority (because the write should originate from the engine that produced the answer, or from a new dedicated `iagent-artifact-writer` service, or directly from the supervisor's Dagster materialization), Hop 1's scope changes substantively: the write-helper moves to a different component, the bundle-assembly point has to be re-located, and the SSE event flow has to be re-wired so that the writer (wherever it now lives) has the bundle in its hands. The projector (Hop 2) and the read-side swap (Hop 3) are unchanged by the rejection; only Hop 1 is.

**Uncertainty flagged:** The "trailing-steps-nonfatal" interaction is real but not fully specified. The cleanest interim shape is: complete the SSE stream FIRST (user gets the answer), then write to Neo4j (the durability is best-effort within a short retry window). The risk: an answer the user saw is not durable. The alternative — write BEFORE the SSE `stream_end` — couples user-visible latency to Neo4j health. The Restate successor cleans this up (the handler is the durable thing; cortex-bff fires-and-forgets the invocation), but the interim needs an explicit answer the architect signs off on. Build-session sequencing: this is a Hop 1 sub-decision the build owner picks with architect cover.

### Decision 1 — CDC vs polling for Neo4j → projector (REVISED: poll-as-interim, not the settled answer)

**Choice: short-interval polling against Neo4j with an `updated_at`-driven cursor — LABELED INTERIM, with named successor.** Poll is the self-contained interim, not the settled answer. The settled answer is the Restate+topic successor named below and in §3.5's Through-line.

**Coupled to Decision 3.** Polling has no native position primitive, so a hand-built watermark (Decision 3) becomes necessary as the position substitute. Decisions 1 and 3 are **coupled interim mechanisms** per `[[coupled-interim-mechanisms-retire-together]]` — this plan is the first banked instance of that rule. They retire **together** under the same successor; neither retires independently. The shared retirement is what makes the watermark not become orphan scaffolding when the poll loop is eventually replaced.

**Reasoning — why poll wins as the self-contained interim:**

- **Neo4j Enterprise is dead by choice, not by ignorance.** The deployed image is `neo4j:5.26.0` (community edition by tag, plugins `["apoc", "n10s"]`). Neo4j CDC is an Enterprise feature. The architect's review confirmed: **Enterprise is not desired** (the licensing cost/exposure is not worth the latency gain for this phase). This kills the CDC-on-Neo4j-Enterprise option permanently; `CALL dbms.components()` remains a build-step-zero positive confirmation that the deployed image is what the audit says, but Enterprise is not on the table even if it were sitting in the registry.
- **The streaming third option exists in our toolchain but is not yet usable here.** Redpanda runs in the sandbox (DataHub uses it; openddil's streaming-ingest path uses it). The natural Restate+topic successor (see below) consumes a topic feed. But: **community Neo4j has no CDC emitter, so something has to get the write onto a topic.** The clean version is cortex-bff dual-writing (Neo4j + topic emit) inside a Restate handler — see successor — but standing that up requires Restate to own the artifact write path, which expands the Hop 1 scope past what this phase needs.
- **Why dual-write without Restate is rejected:** a naive dual-write (cortex-bff commits to Neo4j, then emits to Redpanda) is a two-target write with no both-or-neither guarantee. This is the project's signature failure mode (unenforced contract between components — Neo4j commits, the emit fails, the graph and read-side silently diverge — and the symptom is invisible until a downstream reader notices a row that should exist doesn't). **Making dual-write correct pulls in exactly-once machinery via Restate, which is the successor below.** Putting Restate in front of cortex-bff's write path is the right answer; doing it now is the wrong time.
- **Poll wins as the self-contained interim** because it avoids all of that: no topic, no exactly-once contract, no new failure modes in cortex-bff's request path, no dependency on Restate. It honors "don't add deps unless needed" and gets the substrate proven end-to-end. The interim is throwaway scaffolding labeled as such. Poll details: `updated_at`-indexed Cypher query, 500ms interval, idempotent upsert keyed by `artifact_id`, restart-safe cursor.
- **Latency budget (interim-acceptable):** 500ms poll → P50 round-trip from Neo4j-commit to Postgres-projected ~750ms, worst-case ~1s. Inside the canvas budget for the interim. The successor (offset consumption) drops P50 toward ~50ms — but the interim doesn't need that yet.

**The successor — named on paper, NOT built this phase:**

When cortex-bff's Redpanda emit exists for **independent reasons** (the streaming-ingest integration that is coming anyway for other parts of the platform), the AnswerArtifact write moves behind a Restate handler. The handler owns the write as durable, exactly-once execution: step-1 Neo4j write, step-2 topic emit, both journaled in Restate. This is **NOT a distributed transaction across Neo4j+Redpanda** (nothing gives that cheaply; 2PC is overkill) — it's durable execution: if the handler crashes after the Neo4j write but before the emit, Restate resumes from the journal and drives the unfinished step to completion exactly once. cortex-bff shrinks to "invoke Restate to persist this artifact"; Restate owns the durability.

The projector then becomes a **topic consumer** instead of a poller. The poll loop deletes. The watermark deletes (Decision 3 retires; offset becomes the position). This is openddil's exact pattern with Neo4j added as a second write target inside the durable handler — a pattern the platform already runs and trusts.

**The trigger for the flip:** Redpanda becomes load-bearing for cortex-bff for reasons beyond this projector. Until then, Restate stays out — pulling it in now adds the dependency before it's needed. The decision to flip is *not* about projector performance; it is about the moment cortex-bff already has a Redpanda emit path for other reasons, at which point hooking the projector to it costs almost nothing and the interim becomes pure liability.

**Rejection trigger:** If the architect rules the interim should be skipped entirely (because pulling Restate in now is cheaper than the eventual flip cost), Decisions 1 and 3 both collapse into the successor immediately. Hop 2's scope expands to include a Restate handler in front of cortex-bff's write path AND a topic consumer projector. Hop 3 is unchanged. Plan timeline lengthens but interim scaffolding never gets built. **Alternative rejection:** if the architect rules Enterprise CDC is on the table after all, swap to CDC-into-Redpanda and the projector consumes the topic — same as the successor minus the Restate handler. Decision 3 still retires (offset is the position). Decision 0's "via-Restate-later" footnote shortens because Restate's role contracts.

**Uncertainty flagged:** The community-vs-enterprise edition determination is from indirect evidence (image tag with no `-enterprise` suffix, plugins list, default config). The build session's first step remains the positive confirmation (`CALL dbms.components()` from within the cluster, which the build session has the permission posture to run). If the deployed Neo4j is in fact Enterprise, this decision's framing is unchanged — Enterprise CDC is dead by choice — but the audit's accuracy claim has to be corrected.

### Decision 2 — Postgres projection shape

**Choice: one wide table per archetype-class, with a `kind` discriminator column AND a small set of typed-JSON sub-columns for substructures.** Specifically: one `answer_artifact_projection` table (the canvas's primary read source), with `kind = 'AnswerArtifact'` discriminating it from the future `PublishedArtifact` rows that ADR-0024 Part B will project into the same table. Substructures (`routing`, `sources`, `graph_trace`, `rendered_output`) live as typed-JSONB columns, NOT as separate join-tables.

**ACCEPTED post-architect-review.** One sharpening to record: the `kind` discriminator is **load-bearing, not a convenience column**. It prevents `PublishedArtifact`'s deliberate-nulls (null `rendered_output`, null `sources`, null `routing` per ADR-0024 Rule 1 — "Reference only, no copies") from being rendered as a *broken AnswerArtifact* by a read-path that doesn't know which kind of row it's looking at. This is the same honest-empty-vs-broken distinction the dangling-reference rule (Rule 4) makes, now at the table layer. A `PublishedArtifact` row with null `rendered_output` is *correct and complete* for its kind; the same nulls on an `AnswerArtifact` row are a *broken artifact*. The discriminator gives the read-path the information it needs to render either honestly. The `@projection-published-not-rendered-as-empty-answer` fixture belongs to the Part B publish suite (already updated per the architect's review — `[[fixture-must-exercise-paths]]`); it is not in this projector's probe set, but the table shape is what makes that fixture's path even exist.

**Reasoning:**

- The canvas read shape is `useCurrentArtifact()` returning a fully-populated `Artifact` row — routing + sources + graph_trace + rendered_output assembled together. A read-path that hits one row (no joins) matches the selector shape directly. JSONB is the right primitive for fields the projector has already denormalized.
- ADR-0024 Part B introduces `PublishedArtifact` as a separate archetype that gets projected to the same read-side. **One table per archetype** (the ADR-listed first option) would mean a `published_artifact_projection` table AND consumer code that knows to query either table per context. **One wide table with discriminator** (the chosen option) lets the canvas read-path treat both archetypes uniformly when shared selectors apply (e.g., "all artifacts authored by this user") and discriminate when they differ. The trajectory matches: when Part B lands, the projector emits rows with `kind = 'PublishedArtifact'` into the same projection table; the read shape grows columns nullable for the kind they don't apply to. **The discriminator's load-bearing role is the reason this shape was chosen over one-table-per-archetype**, not just a convenience — without it, the two archetypes' deliberate-nulls collide indistinguishably.
- JSON-payload-with-typed-headers (option 3 in the ADR) is rejected as the primary shape because it puts ALL non-key fields in one JSON blob — which collapses queryability of typed fields (`valid_as_of`, `status`, `produced_for.user_id`) into JSON-path expressions. Those fields are queried by name often enough to be top-level columns. The sub-structures (`routing`, `sources`, `graph_trace`) are JSONB because they ARE assembled blobs from the Neo4j side and don't need per-field queryability at the canvas read layer.
- Schema migration cost when new edge types land: the four standards edges (ADR-0023's reserved vocabulary, ADR-0024 Part A) instantiate per-demand. When `PRODUCED_BY_PROCESS` lands, the projector either (a) folds the BPMN process URN into a nullable top-level column, or (b) extends the `routing` JSONB to carry it. Either is a migration the projector PR ships; neither requires re-shaping the table.
- The Electric Shape API works naturally on a single table with a `WHERE` filter (Electric's "shape" is essentially `SELECT ... FROM table WHERE condition`). A wide table with a discriminator maps directly to a shape; one-table-per-archetype would mean separate shapes the client has to merge.

**Rejection trigger:** If the architect rules `PublishedArtifact` should be a separate table (because the ADR's "instances vs classes" distinction is load-bearing differently than this plan reads), swap to one-table-per-archetype with shared FK to a small shared `actor` table for the producer/consumer references. The hop-2 acceptance probe shape stays the same; only the schema migration script changes. **Alternative rejection:** if the architect rules JSONB sub-columns are not future-proof enough (because `[[ui-contract-assumed-not-published]]` argues for per-field publication), split `routing`, `sources`, `graph_trace` into related tables; canvas reads then hit a `LEFT JOIN ... LATERAL` shape. Higher query cost, more migrations, but per-field discoverability.

### Decision 3 — Position advertisement (REVISED: spike Electric-native position FIRST; watermark only if needed; coupled to Decision 1)

**Choice (revised): the build session's FIRST step is a one-day spike characterizing Electric's native per-shape position semantics. The watermark is built ONLY if the spike proves Electric's native position is insufficient for the see-your-write contract. If Electric's native position is sufficient, the bespoke watermark is never built — the interim leans on Electric, the successor leans on the topic offset, and the parallel counter never exists.**

**Coupled to Decision 1.** This is the canonical case `[[coupled-interim-mechanisms-retire-together]]` was banked from. The watermark exists *only because* polling has no native position primitive — choosing poll (Decision 1) caused the need to invent a position substitute. When the Restate+topic successor (named in Decision 1's body and §3.5) lands, **both** Decisions 1 and 3 retire at the same moment: the poll loop is replaced by topic consumption, and the topic offset becomes the position (the bespoke watermark never exists in the successor). Naming them as coupled in writing is what prevents the watermark from becoming orphan scaffolding when the poll loop is eventually replaced.

**Why this was sent back from the original draft:**

1. **The coupling to Decision 1 was missed.** The original plan treated Decisions 1 and 3 as independent. They are not — polling is what *causes* the need for a hand-built position primitive. The streaming successor gets position for free. Writing the watermark as a stand-alone permanent invariant (which the original draft implicitly did) would have built scaffolding nobody knew when to retire.
2. **The watermark's ordering invariant was untested.** The watermark's see-your-write contract is "client waits until `projector_watermark.value ≥ N`, then trusts the view is current." But the projector commits the artifact row and the watermark row as **two upserts**, and Electric syncs them as **two separate shapes with no stated cross-shape delivery-ordering guarantee**. If the client sees `projector_watermark = N` arrive *before* the artifact row tagged with watermark N, it concludes "visible," reads the store, and the artifact isn't there. **That's a see-your-write violation that looks exactly like a flaky test and would be hell to diagnose.** It is an assumed contract about Electric's delivery semantics that the original plan's three hop probes did not test — the project's dominant failure mode (`[[ui-contract-assumed-not-published]]`, `[[feedback-integration-positive-controls]]`) reproduced inside the projector itself.

**The spike — required BEFORE Hop 2's projector code lands:**

- **Goal:** characterize Electric's native per-shape position semantics and cross-shape delivery ordering. Specifically: when the client subscribes to a single shape that includes both `answer_artifact_projection` and `projector_watermark` rows (or a single combined shape that includes the watermark as a derived field of the artifact row), does Electric guarantee in-order delivery within the shape? When the client subscribes to two separate shapes, are cross-shape ordering guarantees stated?
- **Cheaper to answer than to build a parallel counter and discover it races**, per the architect's framing. The spike is bounded to a day; it may delete Decision 3 entirely. Don't build a watermark you spike your way out of an hour later.
- **Spike output:** either (a) "Electric's native position is sufficient — drop the watermark, use Electric's per-shape position as the see-your-write primitive," in which case Decision 3 collapses and Hop 3's probe asserts against Electric's native position; or (b) "Electric's native position is insufficient — build the watermark, AND build the see-your-write ordering probe described below."

**If the watermark IS built (spike outcome b):**

The original draft's watermark mechanics stand — projector-local monotonic sequence, recovered from `SELECT MAX(watermark)` at restart, published via HTTP endpoint AND as a synced row, returned by cortex-bff in the SSE `stream_end` event. **Plus** Hop 3 gains a fourth probe assertion: see-your-write ordering.

The fourth probe assertion (load-bearing, must be able to fail):

```
GIVEN the projector is running and the watermark is built.
WHEN cortex-bff writes an artifact (returns watermark = N)
AND the client immediately calls await_until_watermark(N)
AND then synchronously reads useCurrentArtifact() for the written id.
THEN the artifact is present in the store.

The probe is made able to fail by ARTIFICIALLY DELAYING the artifact-row sync relative to the watermark-row sync (slow-network simulation or controlled inject in the test harness). If with the artifact-row delayed and the watermark-row arriving first, the wait-until-watermark + synchronous read finds the artifact absent, the see-your-write contract is violated AS IT WAS IN PRODUCTION RACE WINDOWS, and the watermark is decorative — the design has to add either:
  (i) ordering inside Electric (publish both as one shape, lean on within-shape in-order delivery), OR
  (ii) ordering in the projector apply (write the watermark row to Postgres AFTER the artifact row, and rely on Postgres commit ordering — which only helps if Electric reads them in commit order).
```

Per `[[pre-written-fixtures-must-fail-first]]` — show the see-your-write probe RED first (with the artifact-row sync delayed, the assertion has to fail), then implement whichever ordering fix is needed, then re-run and trust GREEN. A watermark whose see-your-write probe has only ever been green-without-having-been-red is decorative.

**Rejection trigger:** If the architect rules the spike is overkill (because Electric's native position is documented and the team trusts the docs), skip step (a) and adopt Electric's native position directly. Decision 3 collapses without a spike. **Alternative rejection:** if the architect rules the see-your-write contract is itself not load-bearing (clients tolerate "the artifact appears within ~2s" without a wait-until primitive), drop the position-advertisement entirely. The cost is a worse UX during pending → complete; the gain is one fewer mechanism in the interim.

**Build-sequencing implication (binding):** The Electric-native-position spike runs BEFORE Hop 2's projector code, per the architect's explicit guidance. See §3.6 Build-session gate list.

### Decision 4 — Where the projector runs

**Choice: a new Deployment named `iagent-projector`, deployed via a new helm template `templates/projector.yaml`, mirroring the cortex-bff shape (single replica, env-driven config, no PVC needed — projector state lives in Postgres). It runs as its own process, with its own lifecycle independent of cortex-bff. The Electric server runs alongside as a sibling Deployment (`iagent-electric`) — distinct because Electric has its own lifecycle, exposed port, and image.**

**Reasoning:**

- **Lifecycle independence:** the projector's apply loop should not restart whenever cortex-bff restarts (which happens on every cortex-bff deploy). Conversely, a projector restart should not impact cortex-bff's request path. Co-locating them couples lifecycles in a way that creates outages when none is required.
- **Auth surface:** the projector needs Neo4j credentials (poll-side) AND Postgres credentials (apply-side). Both already exist in the chart (`.Values.neo4j.auth`, `.Values.postgresql.auth`). Mounting them onto a dedicated projector Deployment is one env-config block; mixing them into cortex-bff expands cortex-bff's credential surface for no benefit.
- **Observability seam:** the projector logs go to a labeled pod (`app=iagent-projector`) that is grep-able as a unit. The **liveness probe asserts the apply loop is ADVANCING, not just that data is correct** — per `[[liveness-probe-watches-advance-not-just-correctness]]` (banked from this plan's §7 footnote in the original draft, elevated by the architect to its own rule). The advance check reads the watermark (if built per Decision 3) or the projector's apply-tick counter (if Decision 3 collapses), and asserts the value at T+1s is greater than the value at T-0 when the source has writes. A correctness-only probe (e.g., "are the rows shaped right") misses the frozen-but-correct failure mode — a projector that ran once, projected the table, then died has identical data to a healthy projector; only the advance check distinguishes them. A readiness probe verifies the Neo4j and Postgres connections are healthy. If the projector is stuck, the sandbox finds out via the readiness probe failing — which it cannot do if the projector is embedded in cortex-bff. **The liveness probe must itself be verified can-fail per `[[pre-written-fixtures-must-fail-first]]`**: kill the projector's apply loop, watch the probe go red. If the probe stays green when the loop is dead, the probe is checking the wrong thing.
- **Why not a Dagster sensor:** a sensor is one of Dagster's polling primitives, but the projector is not a Dagster asset and shouldn't appear in the Dagster graph. Dagster runs already have their own materialization assets (`subtask_routing_decision`, `subtask_graph_trace`, `subtask_sources`). Adding the projector as a sensor conflates Dagster's role (orchestration of pipeline runs) with the projector's role (CQRS read-side maintenance).
- **Why not a sidecar to Neo4j:** Neo4j runs as a StatefulSet; sidecars to StatefulSet pods complicate the volume/restart story for no operational gain. The projector is network-attached to Neo4j over bolt, same as any other client.
- **Why distinguish projector and Electric server:** Electric is a third-party server with its own release cadence and image. Bundling its lifecycle with the projector means upgrading Electric requires re-rolling the projector and vice versa. Distinct Deployments let each upgrade independently. The two communicate over Postgres (Electric reads from Postgres just like any other consumer).
- **`[[sidecar-registry-pattern]]` does NOT apply here.** That pattern is for self-describing user-deployments that register their domain assets with the central broker. The projector is infrastructure — it is not a user-deployment and it doesn't advertise domain content.

**Rejection trigger:** If the architect rules the projector should be embedded in cortex-bff (because operational simplicity > lifecycle independence at this stage), fold the projector loop into cortex-bff's startup as a background task with its own asyncio task. The probe shapes change (the projector-loop-stuck signal now has to surface through cortex-bff's health endpoint), and a cortex-bff restart triggers a brief catch-up window on the projector watermark. **Alternative rejection:** if the architect rules Electric and the projector should be one binary (because cortex governs both halves of the CQRS pair per ADR-0023), then the projector image bundles a small embedded Electric-like sync — this materially increases project scope and is unlikely; raised only because the ADR explicitly says "cortex governs both halves."

### 3.5 Through-line — interim vs successor, on record

The plan is staged in two named phases. The current phase ships the interim; the successor is on record so future readers know which mechanisms are throwaway scaffolding and what trigger flips between them.

**Current-phase shape (the interim, what this plan builds):**

```
cortex-bff direct write → Neo4j → projector polls → Postgres → Electric → cortex-ui store
```

- **cortex-bff** assembles the bundle today (as it does for the SSE path), adds an idempotent Neo4j write (Decision 0). The write is best-effort within a short retry window AFTER the SSE stream completes, to keep user-visible latency decoupled from Neo4j health.
- **Projector** polls Neo4j on a 500ms cursor (Decision 1, interim), upserts into the wide-table-with-discriminator (Decision 2, accepted as permanent), advances either Electric's native position or a bespoke watermark per Decision 3's spike outcome.
- **Electric → store**: client subscribes, store stops being SSE-fed (Hop 3).

**Successor shape (named on paper, NOT built this phase):**

```
cortex-bff → Restate handler → (Neo4j write + Redpanda emit) → projector consumes topic → Postgres → Electric → cortex-ui store
```

- **cortex-bff** shrinks from "writer" to "invoker." It hands the bundle to a Restate handler and is done. Decision 0's via-Restate footnote.
- **Restate handler** owns the durable write: step-1 Neo4j commit, step-2 Redpanda emit, both journaled. NOT 2PC — durable execution. Crash between steps → resume from journal → drive the unfinished step exactly once. This is openddil's exact pattern with Neo4j added as a second target.
- **Projector** consumes the Redpanda topic. The poll loop deletes (Decision 1 retires). The bespoke watermark deletes (Decision 3 retires; offset becomes the position). The projector is a stateless topic consumer.
- **Postgres → Electric → store** unchanged (Decision 2 accepted as permanent; only the upstream changes).

**The trigger that flips between them:** Redpanda becomes load-bearing for cortex-bff for **reasons beyond this projector** — typically the streaming-ingest integration that is already on the platform's roadmap. The flip is **not** triggered by projector performance or by a desire to retire the interim for its own sake; it is triggered by the moment cortex-bff already has a Redpanda emit path for other reasons, at which point hooking the projector into it costs almost nothing and the interim becomes pure liability.

**What retires together (the coupling, on record):**

| Mechanism | Phase | Retires with |
|---|---|---|
| Decision 0 — cortex-bff direct write | Interim | Restate handler (cortex-bff becomes invoker) |
| Decision 1 — polling | Interim | Topic consumption |
| Decision 3 — bespoke watermark (if built) | Interim | Topic offset becomes position |
| Decision 2 — wide table + discriminator | Permanent | — |
| Decision 4 — separate Deployments | Permanent | — |

The interim trio (Decisions 0, 1, 3) retires under a **single shared successor** (the Restate+topic path). Per `[[coupled-interim-mechanisms-retire-together]]` — this plan is the first banked instance of that rule. The retirements are coupled by their shared cause (no streaming change-feed today); when that cause is removed (Redpanda emit exists), all three exit at once. **Naming this in writing is what prevents the watermark from becoming orphan scaffolding the team forgets to retire.**

### 3.6 Build-session gate list (binding sequence)

The build session opens with this gate list. Each gate is a positive-confirmation step, not an assumption. Out-of-order execution is a premise-shift requiring architect re-review.

1. **Confirm Neo4j edition.** `CALL dbms.components()` from inside the cluster. Predicted: community. If Enterprise, re-evaluate Decision 1's framing (Enterprise CDC remains dead by choice per the architect's review, but the audit's accuracy claim has to be corrected before further steps).
2. **Run the Electric-native-position spike (one-day budget).** This runs BEFORE Hop 2's projector code. Outcome decides whether Decision 3 collapses (use Electric's native position, no watermark built) or stands (build the watermark + the see-your-write ordering probe). The architect was explicit: "It may delete Decision 3 entirely, and you don't want to build a watermark you spike your way out of an hour later."
3. **Hop 1 — cortex-bff becomes the Neo4j write authority (Decision 0).** Probe written first (red), code lands, probe goes green. Trailing-steps-nonfatal interaction (write AFTER SSE stream_end, or BEFORE — the build owner picks with architect cover per Decision 0's uncertainty flag).
4. **Hop 2 — projector (poll loop or whichever Decision 1 settled on).** Probe written first (Phases A, B, C all red where applicable), code lands, probes go green. Liveness probe verified can-fail by killing the apply loop and watching it go red, per `[[liveness-probe-watches-advance-not-just-correctness]]` and `[[pre-written-fixtures-must-fail-first]]`.
5. **Hop 3 — Electric → store swap.** Part 1 (byte-identical diff probe) and Part 2 (propagation without SSE) both run; if Decision 3 stood after the spike, Part 3 (see-your-write ordering probe with artificially-delayed artifact-row sync) also runs. Per `[[pre-written-fixtures-must-fail-first]]`, see-your-write probe goes RED first (with the delay injected, the wait-until-watermark + synchronous read finds the artifact absent), then the ordering fix lands, then the probe goes green.
6. **Visual confirmation per `[[verify-subtle-acceptance-by-inspection]]`.** Open Neo4j browser, open Postgres, open cortex-ui DevTools. Confirm by eye that the data flows match the predicted shapes. Don't accept "all green" without the visual sweep.

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
- **Part 3 (conditional) — see-your-write ordering probe is GREEN AND was red before the ordering fix landed.** Required only if Decision 3's spike outcome required building the bespoke watermark. Probe shape: write artifact (returns watermark = N) → `await_until_watermark(N)` → synchronous `useCurrentArtifact()` read → assert artifact present. Made able-to-fail by artificially delaying the artifact-row sync relative to the watermark-row sync; per `[[pre-written-fixtures-must-fail-first]]`, the probe must be observed RED with the delay injected before the ordering fix lands. If Decision 3 collapsed after the spike (Electric's native position is sufficient), this part is replaced by an equivalent probe against Electric's native position; if Decision 3 collapsed entirely (no see-your-write contract), this part is dropped.
- A manual canvas check: type a query in the running cortex-ui, watch the pending → complete transition, watch the Sources card populate with a URN that matches `subtask_routing_decision`'s `subject_uri` in the corresponding Dagster run. This is the Monday-handoff visual proof.
- Optional but recommended: shut down the SSE path entirely for one test session and confirm the canvas still works end-to-end via Electric alone. (If it doesn't, the SSE path is still load-bearing and the swap is incomplete.)

## 7. Cross-cutting discipline

These rules apply across all three hops. Each hop's plan references them above; this section makes them load-bearing in one place.

- **Integration probe per contract, each able to fail.** Per `[[feedback-endpoint-probe-per-engine]]` and `[[feedback-verification-must-fail]]`: every hop's probe predicts a SPECIFIC value AND a SPECIFIC change-propagation. A probe that returns "all green" because the readback cache stayed warm, or because the projected row was the mock all along, is the always-green anti-pattern this stack now codifies as a recognized class. The Phase B "update propagation" assertion in Hop 2's probe is the canonical instance: insert-only projectors look complete until update arrives.

- **Pre-written fixtures must fail first.** Per `[[pre-written-fixtures-must-fail-first]]`: each hop's probe is written BEFORE the hop's code, and is shown FAILING before the hop's code lands. The red-green transition is the proof. Specifically:
  - Hop 1: probe written, predicted-RED is "no AnswerArtifact node in Neo4j" — confirm RED before adding the cortex-bff Neo4j writer.
  - Hop 2: probe written, Phase A predicted-RED is "row not in answer_artifact_projection" — confirm RED before deploying the projector. Phase B's update-propagation must ALSO go red before code, NOT just degenerate-green by accident of the insert path. **The projector's liveness probe is itself subject to this rule** — kill the apply loop, watch the liveness probe go red, then trust green afterward.
  - Hop 3: byte-identical-diff probe is degenerate-green pre-swap; Part 2 must go RED before Electric is deployed. **If Decision 3's spike outcome required building the watermark, Hop 3's see-your-write ordering probe (Part 3) goes RED with the artifact-row sync delayed before the ordering fix lands, then GREEN after.** A watermark whose see-your-write probe has only ever been green-without-having-been-red is decorative.

- **Liveness watches advance, not just correctness.** Per `[[liveness-probe-watches-advance-not-just-correctness]]` (banked from this plan's original §7 footnote, elevated by the architect): the projector's liveness check asserts the loop is ADVANCING — watermark increments, apply-tick counter increments, cursor moves — not just that data is currently correct. Frozen-but-correct is the failure mode a correctness-only probe misses. A stopped projector with a backfilled-once table is data-identical to a healthy projector; only the advance check distinguishes them.

- **Coupled interim mechanisms retire together.** Per `[[coupled-interim-mechanisms-retire-together]]` (banked from this plan's Decision-1/Decision-3 coupling; this plan is the first instance): the interim trio of Decisions 0, 1, and 3 retires together under the Restate+topic successor. The retirements share a single cause (no streaming change-feed today); they exit together when that cause is removed. The watermark is NOT permanent substrate even if it survives Hop 2; it is throwaway scaffolding whose retirement is documented in §3.5.

- **Verify by inspection, not by attestation.** Per `[[verify-subtle-acceptance-by-inspection]]`: when the agent reports a hop green, the architect (or a different reviewer) opens the actual diff and the actual probe output. Specific inspections this plan calls out:
  - Hop 1: open Neo4j browser, see the node + edge shape match the predicted property names. Don't accept "the probe passed" without the visual confirmation.
  - Hop 2: `kubectl logs deployment/iagent-projector` to confirm the apply loop is actually running. A stopped projector with a backfilled-once table looks identical to a healthy projector from the probe's vantage — the advance-check liveness probe is the structural defense against this.
  - Hop 3: open the cortex-ui DevTools, inspect the zustand store state across an update, confirm the update arrived via Electric subscription (not via an SSE event handler).

- **Halt on premise-shifts.** Per `[[feedback-baseline-regression-gate]]` and the discipline this plan inherits: if the build hits a substrate-shape that wasn't in the audit (e.g., Neo4j turns out to be Enterprise after all, Postgres has a schema migration the architect didn't bless, cortex-bff's deploy story prevents the projector Deployment from being added, the Electric-position spike returns a third-thing outcome neither the plan anticipated), HALT. Surface the premise-shift. Do not silently pick. This plan's audit is the baseline; deviations from it require architect acknowledgment before they get built around.

- **Fixture richness before hardening.** Per `[[fixture-must-exercise-paths]]`: each hop's probe exercises NOT just the happy path. Hop 1's probe exercises both initial-write AND pending-sentinel-refinement AND idempotent-replay. Hop 2's probe exercises insert AND update AND idempotent-poll AND liveness-can-fail. Hop 3's probe exercises type-contract-stability AND propagation AND update-without-SSE AND (if watermark is built) see-your-write ordering with delayed artifact-row sync. The probe suites are richer than "did the row appear"; they exercise the paths the binding contracts care about.

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

**This revised-plan commit is the STOP point.** Binding. The original draft was `ded7cc7`; this revision sits on top of it preserving the review audit trail.

This thread does NOT:
- Write backend code (no Neo4j writer in cortex-bff, no projector Deployment, no Electric Shape).
- Modify any helm chart (no new templates, no values changes).
- Write to any database (Neo4j read-only via inspector existing today; Postgres untouched).
- Change the cortex-ui Artifact type (zero diff against `src/api/types.ts`).
- Run the Electric-native-position spike (that's the build session's first gate, per §3.6).
- Open the build session.

The architect's review of this plan (with a second agent challenging the four decisions specifically) is the next step. The build session is the step after that, gated on architect sign-off on whichever subset of the four decisions survives review.

If, in the moments after this commit, the pull arrives to "just sketch hop 1's Neo4j write while I'm in here" — STOP. The architect's review is the next step; the build is the step after that. Skipping the review collapses the premise-shift surface into the build, which is exactly the discipline-failure the four-decision section is structured to prevent.
