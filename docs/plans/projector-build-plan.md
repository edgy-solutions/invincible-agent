---
status: Plan (LOCKED — Decision 3 RESOLVED by spike fe14d67 + Option C ruling; ALL gates 1-6 closed; build complete through Hop 3 with Monday-handoff substrate proof captured)
date: 2026-06-27
authors: claude (plan-only session, final revision folds in spike outcome + Option C ruling)
gates: ADR-0023 (read side) + ADR-0024 Part B (publish backend dependency)
revision: 3 — Decision 3 RESOLVED Option C (watermark is a COLUMN on every artifact row, not a separate row, not a separate shape). Hop 3 Part 3 DROPS (ordering invariant dissolved — there are no two things to order). Decision 4 liveness probe REVISED (reads internal cursor, not a synced watermark row; `GET /projector/watermark` endpoint survives, only the synced row dies). Hop 2 Phase D EXPANDED (watermark-advanced co-required with durability_status orthogonal propagation). Prior revisions: ded7cc7 (original), 07023ce (Decision 0 + interim/successor), 0c2f5fe (Decision 0 sub-decision settled). Spike outcome: fe14d67.
---

# Projector build plan — Neo4j → Postgres → Electric

## 1. Goal

This plan covers the Neo4j → Postgres → Electric projector seam that ADR-0023 names in its "Open questions for the implementing PR" section. The projector is a real component, not a phrase. Landing it unblocks two threads simultaneously: (a) ADR-0024 Part B's publish backend (which cannot start until the projector exists, per the ADR's explicit sequencing note), and (b) the Phase 1 "Monday handoff" runtime-contract check (URN appearing in `subtask_routing_decision` materialization + Sources card populated end-to-end against a real backend rather than the current SSE mock).

This plan describes **what to build, in what order, with what acceptance probes, and what discipline holds across all three hops**. It states five premise-shift decisions explicitly (Decision 0 elevated post-review, plus the original four) so the architect can challenge each on review. It does NOT cover the publish backend itself, click-to-recall, ADR-0024 Part A's standards integrations, or any UI metaphor decisions about how artifacts arrange themselves in a workspace.

**Three of the five decisions are interim-with-named-successor.** Decisions 0, 1, and 3 are explicitly labeled as throwaway scaffolding pointing at a single shared successor (cortex-bff → Restate handler → Redpanda topic → projector consumes topic, with topic offset as the position). Decision 3 was RESOLVED by the Electric-position spike (commit `fe14d67`) — the bespoke separate-watermark-row is dead by measured evidence; the watermark is a COLUMN on every artifact row (Option C), which dissolves the see-your-write ordering invariant entirely (no two things to order). Decision 3's watermark column is itself interim — it retires when the Restate+topic successor makes the topic offset the position. See Decision 3 in §3 for the architect's structural-vs-coordinated reasoning, and §3.5's Through-line for the retirement-coupling table.

This session ends when this final-revision is committed. The build session is the next thread (with a separate agent), proceeding directly to Hop 1 — gates 1 (Neo4j edition) and 2 (Electric-position spike) are CLOSED.

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

**Three interim mechanisms are flagged.** Decisions 0, 1, and 3 are explicitly coupled (per `[[coupled-interim-mechanisms-retire-together]]` — this plan is the first banked instance of that rule). They retire together under the same successor named in §3.5's "Through-line — interim vs successor" section. Decision 3 was RESOLVED by spike `fe14d67` to Option C (watermark-as-column on every artifact row); the column is still interim and retires with Decisions 0 and 1 under the Restate+topic successor. See Decision 3 in §3 for the full RESOLVED state and the architect's structural-vs-coordinated reasoning verbatim.

### Decision 0 — cortex-bff as the AnswerArtifact write authority

**Choice: yes — cortex-bff becomes the direct AnswerArtifact write authority to Neo4j as the Hop 1 deliverable. Acknowledged as an architectural change to cortex-bff's role, not a projection of existing data. Conscious yes, not a rider on the projector approval.** Conscious "via Restate later" footnote: when the Restate path lands (per the Through-line in §3.5), cortex-bff stops being the *direct* writer and becomes the *invoker* of a durable Restate handler that owns the persistence. The footnote is load-bearing — it prevents future readers from treating "cortex-bff writes Neo4j" as a permanent invariant of the system.

**Reasoning:**

- The audit (§2.4) confirmed: **no component in invincible-agent currently writes AnswerArtifact-shaped objects to Neo4j.** `src/iagent/gateway.py` line 1908 reads Neo4j for the inspector panel; it does not write. The 20 other files matching `neo4j_driver|GraphDatabase.driver` write ontology-substrate content (subjects, verbs, ROUTING decisions for the ontology layer), not artifacts. The SSE bundle that cortex-bff assembles today is **transient** — it goes out the SSE socket and is lost as soon as the client tab closes. This is the absence of durability the projector plan is named for, and it is the largest single fact in the whole plan.
- cortex-bff is the natural writer because it is **already where the bundle is assembled** — routing decision, sources, graph trace, rendered output all flow through cortex-bff before they are emitted as SSE events to the client. The work of "make this a graph node" is one Cypher write away from work cortex-bff already does. Putting the writer anywhere else (a new service, a sidecar, embedded in an engine) would require teaching that consumer how to receive the assembled bundle.
- This expands cortex-bff's responsibility surface in a material way: it gains write-credentials to Neo4j, gains responsibility for capture-or-lose-forever fields (`valid_as_of`, `produced_for`, `produced_by`, `derived_from_artifact_id`), and gains a new failure mode where a Neo4j outage means user-visible artifacts are lost even if the rest of the pipeline succeeded. The "trailing-steps-nonfatal" discipline (`[[feedback-trailing-steps-nonfatal]]`) applies — the Neo4j write must not break delivery of the SSE bundle to the user; it has to either succeed durably or fail visibly without taking the user's answer down.
- **Why this is a conscious yes and not a rider on Decision 4:** Decision 4 chooses *where* the projector runs. Decision 0 chooses *who writes the source-of-truth*. Those are different decisions. The projector consumes whatever the write-authority produces; the write-authority doesn't have to be cortex-bff in principle (an engine could write directly, or a future Restate handler could). Treating Decision 0 as automatic conflates two architectural choices and skips the architect's chance to challenge the "cortex-bff gains a major new responsibility" framing.

**Via-Restate-later footnote:** The cortex-bff direct-write is **interim, coupled to Decisions 1 and 3**. When Redpanda becomes load-bearing for cortex-bff for independent reasons (the streaming-ingest path that's coming for other reasons), the AnswerArtifact write moves *behind* a Restate handler. The handler owns: step-1 Neo4j write, step-2 Redpanda emit, both journaled. cortex-bff shrinks from "writer" to "invoker of the durable handler." This is NOT a distributed transaction across Neo4j+Redpanda (2PC is overkill); it's durable execution — if the handler crashes between Neo4j write and topic emit, Restate resumes from the journal and drives the unfinished step exactly once. This is openddil's pattern with Neo4j added as a second target inside the durable handler — a pattern the platform already runs and trusts. See §3.5 Through-line.

**Rejection trigger:** If the architect rules cortex-bff is the wrong authority (because the write should originate from the engine that produced the answer, or from a new dedicated `iagent-artifact-writer` service, or directly from the supervisor's Dagster materialization), Hop 1's scope changes substantively: the write-helper moves to a different component, the bundle-assembly point has to be re-located, and the SSE event flow has to be re-wired so that the writer (wherever it now lives) has the bundle in its hands. The projector (Hop 2) and the read-side swap (Hop 3) are unchanged by the rejection; only Hop 1 is.

#### Decision 0 sub-decision — delivery vs Neo4j-write trailing-steps interaction (SETTLED: decouple-with-honest-failure-state)

**Background.** Revision 1 of this plan flagged the trailing-steps-nonfatal interaction as an open sub-decision and posed it as a binary: write-before SSE `stream_end` (couples user latency to Neo4j health) vs write-after (best-effort durability; the user holds an answer not yet in the substrate). The architect rejected the binary outright and ruled the sub-decision in this revision.

**The architect's ruling — verbatim discipline.** The framing was subtly wrong. **Write-after is NOT "best-effort durability"; it is the project's signature dual-write failure mode reintroduced one layer below where Decision 1 just rejected it.** The user saw an answer that the graph-of-record doesn't have, and nothing reconciles them. That is the same shape Decision 1 killed; it just doesn't have the words "dual-write" on it here.

The false premise: that the Neo4j write and the user-visible answer have to be **ordered against each other at all**. They don't. They answer two different questions:

- `stream_end` answers **"did the user get their answer."**
- The Neo4j write answers **"is this answer durable in the substrate."**

**Coupling them in either order is the mistake.** Per the newly banked `[[ordering-questions-hide-coupling-questions]]` — this sub-decision is the first banked instance of that rule. The rule's general statement: when a sub-decision is framed as "in what order do these two operations against two systems happen?", STOP. The framing is usually the trap. The real question is whether they should be coupled at all, and the answer is usually decouple-with-honest-failure-state per-domain. The rule is the planning-layer generalization of the same shape Decision 1's poll/watermark coupling exhibited — **this plan keeps finding pairs of operations it assumed were ordered or independent when they were actually coupled or separable.**

**The settled interim shape — decouple-with-honest-failure-state:**

1. **Delivery at `stream_end` is never coupled to the Neo4j write.** Honors `[[feedback-trailing-steps-nonfatal]]` literally — nothing after `final_answer` can fail delivery. The user gets their answer regardless of Neo4j state.
2. **The Neo4j write is a separate retryable step** that does NOT gate `stream_end`, but is **NOT fire-and-forget either.** The distinction from naive write-after is the failure handling: if the write fails, that is a **known, recorded state** — the artifact is `delivered-but-persistence-pending`. The artifact carries a durability status the same way it carries the existing `status: pending|complete|failed` lifecycle. A delivered answer whose Neo4j write hasn't landed is honestly recorded as `delivered, persistence pending`; retry drives it to durable, or surfaces it as `persistence_failed` if retries exhaust.
3. **The polling projector tolerates the small write-lands-after-delivery window** because it polls on a 500ms cursor anyway (Decision 1). A Neo4j write that lands a second or two after `stream_end` is invisible to the projector's correctness model — the projector applies whatever is in Neo4j when it polls; it doesn't care about when the write committed relative to delivery.

The latency concern (write-before slowing the user) is gone — delivery isn't coupled. The durability gap (write-after losing the answer silently) is bounded — the write is retryable and its failure is a **recorded state**, not a silent drop.

**Continuity proof — why this is the correct interim shape, not just an acceptable one.** Per `[[ordering-questions-hide-coupling-questions]]`'s "successor test": when staging interim → successor, ask whether the successor formalizes the interim's shape or replaces it wholesale. **This interim's shape — decouple delivery from the durable write, record honest partial-completion state, retry per-domain — is EXACTLY what the Restate successor formalizes.** Restate's durable handler does precisely this: deliver, then journal the Neo4j write as a step driven to completion exactly-once with resume-on-crash. The interim is "decouple-with-best-effort + honest recorded state"; the successor is "decouple-with-durable-journaling + exactly-once." They agree on shape; they differ only in the **strength of the durability guarantee**. Write-before and naive write-after **don't** have that continuity — they're shapes Restate would have to undo. The continuity is the proof this is the right interim.

#### `durability_status` — a new artifact concept, separate from `status`

The decouple-with-honest-failure-state shape forces an addition to the AnswerArtifact model: a **`durability_status` field separate from the existing `status` field**.

The two cover **orthogonal questions** and must not be collapsed:

| Field | Question it answers | Values |
|---|---|---|
| `status` (existing, from Phase 1 / ADR-0023) | Lifecycle of *producing the answer*: pending while the pipeline runs, complete when produced, failed if the pipeline errored. | `pending` / `complete` / `failed` |
| `durability_status` (new, this revision) | Whether the produced answer has been **written to Neo4j as the substrate of record**. | `persistence_pending` / `durable` / `persistence_failed` |

A delivered answer can be `status=complete` AND `durability_status=persistence_pending` (delivered, write in flight). It can be `status=complete` AND `durability_status=durable` (the happy steady state). It can be `status=complete` AND `durability_status=persistence_failed` (delivered, write attempts exhausted — the user has the answer, but it is NOT in the graph-of-record; the system honestly knows this).

**Discipline — do NOT collapse `durability_status` into `status`.** Per `[[verify-subtle-acceptance-by-inspection]]`, the temptation is to overload the existing `status` field with new values (e.g., add `persistence_failed` to the `status` enum). That is exactly the neighboring-concept-quietly-carries-a-field trap the rule covers (the canonical case was `Message.payload` quietly carrying an artifact-shaped field). The two questions are orthogonal facts about the artifact; collapsing them re-creates the same concept-conflation class as the persona-conflation, the Message-vs-Artifact conflation, and the canvas-overwrite. **Two distinct concepts get two distinct slots.**

In the Neo4j model: `durability_status` is a property on the `:AnswerArtifact` node (alongside `status`). In the Postgres projection: a separate top-level column (queryable, not buried in a JSONB substructure — because consumers will filter by it: "show me artifacts that need persistence retry"). In the cortex-ui `Artifact` type: a new field with the same orthogonality preserved.

**Lifecycle interaction with retry.** The cortex-bff Neo4j writer attempts the write after delivery. On success: the row goes through Hop 2's projector with `durability_status=durable`. On transient failure: cortex-bff retries within a bounded window; the artifact carries `durability_status=persistence_pending` in the interim. On exhausted retries: the artifact carries `durability_status=persistence_failed`. The Restate successor replaces the bounded-retry-window with crash-safe exactly-once execution, but does NOT change the `durability_status` values or their semantics — the field survives the successor flip unchanged. This is a second instance of the continuity-proof: the interim's data shape is what the successor inherits.

#### Where the ordering-vs-coupling rule will fire again — note for ADR-0024 Part B planning

`[[ordering-questions-hide-coupling-questions]]`'s "Where this rule was about to apply on the publish backend" section calls out three publish-backend sub-decisions that will pose as ordering questions if not caught:

- **Publish action**: PublishedArtifact write to Neo4j BEFORE the target-system emit, or AFTER? Same trap shape. Answer: decouple with honest "publish attempted, target emit pending / failed / succeeded" recorded state.
- **DataHub scrub job**: scrub marks `orphaned` BEFORE the UI sees the dangling state, or AFTER? Trap shape. Answer: scrub runs on its own track; UI reads current `status` honestly whatever it is.
- **SUPERSEDES chain construction**: new PublishedArtifact node created BEFORE the SUPERSEDES edge to the prior is wired, or AFTER? Trap shape. Answer: durable handler manages the create+edge as exactly-once (this is where Restate matters even within iagent, not just at the cortex-bff write boundary).

**This is NOT this plan's job to solve** — they belong to ADR-0024 Part B's planning thread. But noting it here so the Part B planner reads this section and applies the rule prophylactically rather than re-discovering it through the same architect-review challenge cycle.

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

### Decision 3 — Position advertisement (RESOLVED by spike fe14d67 + Option C ruling: watermark is a COLUMN on every artifact row)

**Choice (RESOLVED): the watermark is a `watermark: int64` column on every artifact row (Option C), not a separate row, not a separate shape, not a separate Electric subscription.** See-your-write becomes `max(watermark) over the client's subscribed rows ≥ N` — a single fact derived from the artifact data the client already has. There is no second thing to deliver in order.

**Spike outcome (commit `fe14d67`).** The spike characterized Electric's per-shape delivery semantics. Measured evidence:
- **Cross-shape delivery is NOT ordered.** 15 of 500 trials reordered watermark-row arrival before its corresponding artifact-row at the 15–16 ms boundary. The original separate-watermark-row design would have produced ~3% see-your-write violations in production — invisible to most tests, hell to diagnose when surfaced.
- **Same-shape FIFO holds.** 30/30 trials maintained order when the watermark and artifact were rows in the same shape. This would have made an Option B "watermark-row in same shape" design correct.
- **Option B (same-shape watermark row) is correct by transport-property; Option C (watermark-as-column) is correct by construction.** The spike's measured evidence rules out the original cross-shape design and makes Option B viable, but the ruling prefers Option C for the structural reason recorded below.

**The architect's structural-vs-coordinated reasoning (verbatim, the load-bearing rationale):**

> "The deepest reason Option C is correct rather than just simpler is that it makes the see-your-write guarantee **structural** rather than **coordinated**. With a watermark row (Option B), even in the same shape, the client reconciles two facts: 'the artifact row' and 'the watermark row,' and the correctness depends on per-shape FIFO delivering them in the right order. That works — the spike proved same-shape FIFO holds 30/30 — but it's a guarantee that depends on a property of the transport. With Option C, there is no reconciliation at all. The watermark *is* a field on the artifact. When the artifact arrives, its watermark arrived, because they're the same row. There's no ordering question left to get right, because there are no longer two things to order. Option B is 'correct because FIFO holds'; Option C is 'correct because there's nothing to order.' The second is strictly better — it doesn't just pass the see-your-write test, it makes the test inapplicable. **That's why Hop 3 Part 3 doesn't just become passable, it vanishes.**"

**This is the rule worth surfacing one level up.** Per `[[ordering-questions-hide-coupling-questions]]`'s sibling discipline at a different layer: when an ordering-or-coordination contract is required to make a design correct, the strictly-better move is to dissolve the contract entirely rather than satisfy it. The Decision-0 sub-decision dissolved a delivery-vs-persistence coupling; this Option C ruling dissolves a cross-row-delivery coupling. Same shape of move at two different decision layers in the same plan.

**Mechanics under Option C:**

- **Neo4j AnswerArtifact node** gains a `watermark: int64` property. Set monotonically by the cortex-bff write helper at write time, and **bumped on every UPDATE** — even an update that only changes `status` or `durability_status`. This is the load-bearing rule (see Consequence 2 / Hop 2 Phase D expansion below).
- **Postgres `answer_artifact_projection`** gains a top-level `watermark bigint NOT NULL` column. The projector bumps it on every apply — including applies whose only change is `durability_status` or `status`.
- **cortex-ui Artifact type** gains a `watermark: number` field (TypeScript `number` is sufficient since JS bigint isn't needed at the client; the value fits safely in 2^53 — confirmable budget calculation but uncontroversial at this throughput).
- **`projector_watermark` table is DELETED from Hop 2's schema migrations.** It was the synced-row primitive — Option C eliminates it.
- **`projector_cursor` table SURVIVES** — that's the projector's own internal state for poll-resumability, separate from the per-row watermark. Different concept.
- **The `GET /projector/watermark` HTTP endpoint SURVIVES** — it now reads from the projector's internal apply-tick counter (in-memory or PG-backed via `projector_cursor` extended with a `last_applied_watermark` field). The endpoint is for probes/admin/operability, not for the see-your-write contract (which is now structural per Option C). See Decision 4's revised liveness probe.
- **The cortex-bff `stream_end` event** still returns the issued watermark — the client uses it as the N in `max(subscribed_watermarks) ≥ N`. No `await_until_watermark_row` machinery, no separate subscription.

**Two values, separate facts — explicitly do NOT collapse.** Per `[[verify-subtle-acceptance-by-inspection]]`'s neighboring-concept-trap class: the AnswerArtifact now carries BOTH:
- `valid_as_of` — the as-of of the grounding (ADR-0023's freshness primitive; the time the substrate was sampled at). Semantic, operational, content-side concept.
- `watermark` — the projector's monotonic apply-order position. Mechanical, transport-side concept.

These are orthogonal facts about the artifact. They live in different concept spaces. **Do NOT collapse them under any framing.** A future refactor that says "valid_as_of is monotonic, just use it as the watermark" would re-create the same concept-conflation class as the Phase-1 persona-conflation, the Message-vs-Artifact conflation, and the canvas-overwrite. Two distinct concepts get two distinct slots. The Hop 2 Phase D probe (expanded below) protects against the watermark slot quietly going vestigial; this paragraph protects against it being collapsed in the opposite direction.

**Consequence — Hop 3 Part 3 (see-your-write ordering probe) DROPS.** Not because the projector got cleverer, but because the ordering invariant is dissolved. There are no longer two things to order. A probe for "ordering" requires an ordering contract to validate; Option C has none. The plan must explicitly note that "no probe needed" is the correct outcome here, not a missing probe. The two-shape race window the original Decision 3 needed a probe for cannot exist by construction.

**Consequence — Decision 4's liveness probe shape changes.** With Option C, there is no global synced "projector watermark" row to query; the projector's position lives only in its internal cursor and per-row watermark columns. Decision 4's liveness probe is revised in the Decision 4 observability-seam bullet below to read the projector's internal cursor (via the surviving `GET /projector/watermark` endpoint, which now sources from internal state) instead of a synced row. The discipline of asserting advance per `[[liveness-probe-watches-advance-not-just-correctness]]` is unchanged; the source of the advance signal moves from "synced row" to "internal cursor."

**Consequence — Hop 2 Phase D expands.** Every artifact apply must bump the watermark column, including updates that only change `status` or `durability_status`. A status-only or durability-only update that propagates the row change but leaves `watermark` unchanged would quietly break see-your-write for any client awaiting a *later* write — `max(watermark) ≥ N` could be satisfied by a stale max, or worse, the updated row's unchanged watermark makes the see-your-write reasoning evaluate against the wrong position. Phase D's converse assertion grows a co-required sibling: durability_status propagates AND watermark advanced. Per `[[fixture-must-exercise-paths]]`, Phase D must EXERCISE the durability-only update path (not just status updates) — a fixture that only exercises status updates leaves the durability-only-but-watermark-doesn't-bump trap invisible.

**Coupled to Decision 1 — still interim.** Option C resolves the cross-shape coordination problem, but the watermark COLUMN itself is still interim. Per `[[coupled-interim-mechanisms-retire-together]]`: when the Restate+topic successor lands, the polling loop retires AND the watermark column retires together. The topic offset becomes the position; the per-row watermark column becomes redundant scaffolding. The retirement-coupling table in §3.5's Through-line is updated to record this: the column joins the retirement, it doesn't survive the flip as permanent substrate.

**No further rejection trigger.** Decision 3 is RESOLVED. The spike's measured evidence rules out the original cross-shape framing; the architect's structural-vs-coordinated reasoning rules out Option B (same-shape watermark row); Option C is what proceeds into Hop 2. The build session does NOT re-litigate Decision 3 — it implements Option C.

### Decision 4 — Where the projector runs

**Choice: a new Deployment named `iagent-projector`, deployed via a new helm template `templates/projector.yaml`, mirroring the cortex-bff shape (single replica, env-driven config, no PVC needed — projector state lives in Postgres). It runs as its own process, with its own lifecycle independent of cortex-bff. The Electric server runs alongside as a sibling Deployment (`iagent-electric`) — distinct because Electric has its own lifecycle, exposed port, and image.**

**Reasoning:**

- **Lifecycle independence:** the projector's apply loop should not restart whenever cortex-bff restarts (which happens on every cortex-bff deploy). Conversely, a projector restart should not impact cortex-bff's request path. Co-locating them couples lifecycles in a way that creates outages when none is required.
- **Auth surface:** the projector needs Neo4j credentials (poll-side) AND Postgres credentials (apply-side). Both already exist in the chart (`.Values.neo4j.auth`, `.Values.postgresql.auth`). Mounting them onto a dedicated projector Deployment is one env-config block; mixing them into cortex-bff expands cortex-bff's credential surface for no benefit.
- **Observability seam (REVISED under Decision 3 Option C):** the projector logs go to a labeled pod (`app=iagent-projector`) that is grep-able as a unit. The **liveness probe asserts the apply loop is ADVANCING, not just that data is correct** — per `[[liveness-probe-watches-advance-not-just-correctness]]` (banked from this plan's §7 footnote in the original draft, elevated by the architect to its own rule). Under Option C, there is no synced "projector watermark" row to query — the watermark lives only as a column on each artifact row, and a global `max(watermark)` over the synced rows is a client-side concept, not an operator probe primitive. The liveness probe therefore reads the **projector's INTERNAL CURSOR POSITION** via the surviving `GET /projector/watermark` HTTP endpoint, which now sources from the projector's own in-process state (or from a `last_applied_watermark` field added to the `projector_cursor` table) rather than from a synced row. The endpoint exists for probes and admin tooling, NOT for the see-your-write contract (which Option C makes structural — clients don't need it). The probe asserts the cursor at T+1s is greater than the value at T-0 when the source has writes. A correctness-only probe (e.g., "are the rows shaped right") misses the frozen-but-correct failure mode — a projector that ran once, projected the table, then died has identical data to a healthy projector; only the advance check distinguishes them. **This shape is arguably cleaner than the original synced-row design** — the liveness signal SHOULD come from the projector's own state, not from a row it writes. A readiness probe verifies the Neo4j and Postgres connections are healthy. If the projector is stuck, the sandbox finds out via the readiness probe failing — which it cannot do if the projector is embedded in cortex-bff. **The liveness probe must itself be verified can-fail per `[[pre-written-fixtures-must-fail-first]]`**: kill the projector's apply loop, watch the probe go red. If the probe stays green when the loop is dead, the probe is checking the wrong thing.
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
| Decision 3 — watermark COLUMN on every artifact row (Option C, post-spike) | Interim | Topic offset becomes position; the column becomes redundant scaffolding and is dropped at the same flip |
| Decision 2 — wide table + discriminator | Permanent | — |
| Decision 4 — separate Deployments | Permanent | — |

The interim trio (Decisions 0, 1, 3) retires under a **single shared successor** (the Restate+topic path). Per `[[coupled-interim-mechanisms-retire-together]]` — this plan is the first banked instance of that rule. The retirements are coupled by their shared cause (no streaming change-feed today); when that cause is removed (Redpanda emit exists), all three exit at once. The Option C watermark COLUMN does not survive the flip — the topic offset becomes the projector's position, and the per-row column it currently carries is redundant scaffolding. **Recording this in the table is what prevents the column from becoming orphan scaffolding the team forgets to retire** — even though Option C is structurally cleaner than the original synced-row design, it is still interim, and its retirement is coupled to the same shared cause as Decisions 0 and 1.

### 3.6 Build-session gate list (LOCKED — gates 1 and 2 closed; build proceeds at Hop 1)

The build session opens at gate 3. Gates 1 and 2 are CLOSED by positive evidence recorded in this plan. Out-of-order execution from here forward is a premise-shift requiring architect re-review.

1. **~~Confirm Neo4j edition~~ ✓ CLOSED.** Community confirmed via the deployed image tag `neo4j:5.26.0` (audit §2.2, recorded in revision 1). The image carries no `-enterprise` suffix; Enterprise CDC remains dead by choice per the architect's revision-1 review. The build session does NOT need to re-run `CALL dbms.components()` unless something about the deployed image changes; if it does, that's a new premise-shift requiring architect cover before Hop 1 starts.
2. **~~Electric-native-position spike~~ ✓ CLOSED.** Spike `fe14d67` characterized Electric's per-shape delivery semantics. Cross-shape order is NOT guaranteed (15/500 reorders at the 15–16 ms boundary); same-shape FIFO holds (30/30). Decision 3 RESOLVED to Option C (watermark-as-column, not synced row). See Decision 3 in §3 for the full ruling + the architect's structural-vs-coordinated reasoning. The build session does NOT re-run the spike or re-litigate Decision 3 — it implements Option C.
3. **~~Hop 1 — cortex-bff becomes the Neo4j write authority (Decision 0).~~ ✓ CLOSED.** **Two probes** pre-written and RED-first, then GREEN for the predicted reasons: Probe 1 (`tests/test_hop1_neo4j_writeback.py` — happy-path readback by traversal + idempotent replay with watermark-advanced) AND Probe 2 (`tests/test_hop1_neo4j_write_failure_honest_state.py` — both-legs assertion: delivery decoupled AND honest recorded state). Trailing-steps-nonfatal interaction is **settled** per Decision 0's sub-decision ruling: decouple-with-honest-failure-state, NOT write-before-vs-after binary. The `durability_status` field AND the Option-C `watermark` field are both added to the Artifact type at Hop 1's close. Architect-approved baseline shift for Hop 3's diff probe. **Decoupling shape picked: shape 1 (local fallback queue / in-process durability registry)** — per Decision 0 sub-decision's continuity-with-Restate-successor proof; the registry's recorded `persistence_failed` state is what Probe 2's Assertion B reads. Implementation: `src/iagent/answer_artifact_writer.py` (new module) + `src/iagent/gateway.py` (writer dispatch wired after the Graph Path's `stream_end`). cortex-ui type addition: `src/api/types.ts` + minimal `useCanvasStore.ts` initializer change for type-check. See commits below for hashes.
4. **~~Hop 2 — projector poll loop with watermark-as-column.~~ ✓ CLOSED.** Standalone `iagent-projector` Deployment (Decision 4), polls Neo4j on 500ms cursor (Decision 1, INTERIM), upserts into `answer_artifact_projection` with `watermark` and `durability_status` as top-level columns (Decisions 2 + 3 Option C), advances `projector_cursor` transactionally with each apply. Four phase probes all RED-first per `[[pre-written-fixtures-must-fail-first]]`: Phase A (table absent → row never appears), Phase B (insert-only projector → watermark didn't advance, demoed via monkey-patch), Phase C (cursor not honored → apply_count jumped past restart), Phase D (durability_status orthogonal flip skipped → BOTH assertions co-required; Cypher fixture verified by inspection to mutate ONLY `durability_status` + `watermark` per `[[verify-subtle-acceptance-by-inspection]]`). Liveness verified structurally: `GET /projector/watermark` (reads `projector_cursor` from Postgres directly — no in-memory mirror) advanced 22→24 with one fresh write between, apply_count 11→12. Apply-loop stderr shows monotonic batches `last_applied_watermark=24 → 26 → 27`. Implementation: `src/iagent/projector/` (apply_loop + app + __main__), `sql/create_answer_artifact_projection.sql` (idempotent migration), `helm/invincible-agent/templates/projector.yaml` + values entry. Probe: `tests/test_hop2_projector_apply.py`.
5. **~~Hop 3 — Electric → store swap.~~ ✓ CLOSED.** Part 1 (byte-identical-diff probe) RED-first observed (junk field added → "First divergence at line 226" → revert → GREEN), baseline reference literally `496fd8c` in `tests/hop3/test_artifact_type_byte_identical.mjs`. Part 2 (Electric propagation + SSE-absence) Shape A + Shape C combined: Leg A RED proved by pointing `VITE_ELECTRIC_URL` at `http://localhost:9999` (row never arrived in 5s); Leg B RED proved by separate `test_part2_red_proof_legB.mts` that injects an `sse:route_decision` tag and confirms the for-loop fires. GREEN: real ontology URN row inserted to Postgres, arrived in cortex-ui store via Electric within ~500ms, all 9 Electric-covered fields tagged `electric:answer_artifact_projection`, no `sse:*` tags. **Part 3 DROPPED under Option C** — the ordering invariant is dissolved (no two things to order); "no probe needed" is the correct outcome, not a missing probe. Implementation: `templates/electric.yaml` + values entry + Postgres `wal_level=logical` args in `infrastructure.yaml` (invincible-agent); `@electric-sql/client` + `src/lib/electric.ts` + provenance instrumentation in `useCanvasStore` + SSE handler refactor in `useInterviewAgent` (cortex-ui). See commits below for hashes.
> **Footnote (2026-06-27): ADR-0025 lands on top of this gate list, NOT as a new gate.** ADR-0025 (instance-plane access control as provenance) records the access-as-provenance decision and lands two capture-or-lose-forever field additions on top of the Hop-1 write site + Hop-2 projector + Hop-3 Electric path — Capture A (`entitlement_source` flag on `produced_for`, threaded auth.py → gateway → writer → projector → cortex-ui types → store) and Capture B (reserved `access_decision` slot on `Source` / `CITES`, written null today, projected through all five layers). The captures are NOT enforcement — `ENABLE_AGENTIC_AUTH` stays unset, no Topaz calls land, the Zanzibar directory stays unseeded. The captures land the evidence that would otherwise be unrecoverable at decision time; enforcement is a separately-gated session. Because `produced_for` is inline-typed in the `Artifact` interface, Capture A's addition is the **second sanctioned `BASELINE_REF` shift** for the Hop 3 byte-identical-diff probe (the first was Hop 1's `durability_status` + `watermark` additions, which set the current `496fd8c` baseline). See ADR-0025 §Implementation notes for the per-capture commit hashes + the new baseline reference. Capture B does NOT shift the baseline — the field is on `Source`, not on `Artifact`'s inline body.

6. **~~Visual confirmation per `[[verify-subtle-acceptance-by-inspection]]`.~~ ✓ CLOSED in substrate-half.** Monday-handoff SUBSTRATE proof captured (`tests/hop3/monday_handoff_substrate_proof.mts`): a real ontology URN (`https://example.com/ontology/CustomerSegment#NorthAmericanEnterprise`) and a real DataHub-shape source URN (`urn:li:dataset:(urn:li:dataPlatform:datahub,Customer360.NA_Enterprise,PROD)`) reached the cortex-ui store via Electric end-to-end, no mock in the path. The data shape is byte-identical to what `RoutingDecision.tsx` (reads `decision.about.uri`) and `SourcesTrail.tsx` (reads `source.uri`) consume. **The visual eyeball half — a human or browser-driving harness seeing the cards populated in the running canvas — was NOT executed in this thread** (cortex-ui dev server was alive at `http://localhost:5189` against local Electric for the duration of the close; opening the browser is the human's step). **PREMISE-SHIFT SURFACED**: driving the URN end-to-end from a REAL backend query (supervisor's `subtask_routing_decision` materialization → cortex-bff Hop 1 write → projector → Postgres → Electric) requires the full engine fleet locally OR sandbox Postgres with `wal_level=logical`. Sandbox Postgres is shared (Dagster + DataHub etc.); a wal_level flip requires coordinated restart beyond Hop 3 scope. The chart change in `infrastructure.yaml` makes the NEXT sandbox deploy correct; until that deploy, the engine-driven half of the Monday-handoff is a coordinated follow-up. This matches the plan §4 carry-forward language: "Hop 3 closes with the substrate green but the contract proof flagged as pending engine work" — adapted from the `subtask_routing_decision` case to the sandbox-Postgres case.

## 4. Hop 1 plan — AnswerArtifact as a real Neo4j node

### Architect-inspection follow-up (recorded post-`64a4662`)

**Failure mode 1 (pipeline failed → recorded `durable + complete`):** FIXED in the narrow follow-up commit on top of `64a4662`. The writer used to hardcode `a.status = 'complete'` with a comment citing ADR-0023's "never persist pending" rule — the comment was wrong on both counts (assembly is piecewise not upstream; the rule excludes ONE value and does NOT mandate `complete`). Per `[[optimistic-defaults-are-dishonest]]` (this writer is the rule's first confirmed instance) the fix is Option A: `AnswerArtifactBundle.status` is REQUIRED at construction; the writer's MERGE uses `a.status = $status` from the explicit input; the gateway flips status to `'failed'` on every `_perror` branch and to `'complete'` only when `final_payload` arrives and parses cleanly. The dispatch guard refuses to write while status is still `'pending'` (a Graph Path exit was added without a flip). Probe 3 (`test_hop1_pipeline_failure_recorded_as_failed.py`) was RED-first per `[[pre-written-fixtures-must-fail-first]]`: predicted RED was `TypeError: AnswerArtifactBundle.__init__() got an unexpected keyword argument 'status'` (the bundle has no status field); predicted GREEN holds with all four legs (delivery decoupled + `status=failed` + `durability_status=durable` + `rendered_output=null`).

**Failure mode 2 (per-leg absent-vs-empty distinction):** DEFERRED to the publish-backend planning thread (ADR-0024 Part B). The persisted artifact's `sources: []` and `graph_trace: []` are observationally identical to "engine produced empty" vs "engine never reported." Hop 1 does NOT distinguish these — a `complete` artifact with empty sources is treated as "honestly empty." The distinction matters for publish (do not promote an answer whose sources were never reported); the publish backend's planning will add per-field reported-vs-empty machinery when a consumer needs it. Banked at `[[fixture-must-exercise-paths]]`'s publish suite as the `@projection-published-not-rendered-as-empty-answer` shape (related but distinct case).

### Scope

Stand up the write-side under the **decouple-with-honest-failure-state** shape settled in Decision 0's sub-decision. The flow is:

1. cortex-bff completes the SSE stream and delivers the answer to the client at `stream_end`. **Delivery is NOT coupled to the Neo4j write.**
2. Separately (independent track), cortex-bff attempts the Neo4j AnswerArtifact write. Failure of this write does NOT fail delivery; success transitions the artifact's `durability_status` from `persistence_pending` to `durable`; exhausted retries transition it to `persistence_failed`.
3. The artifact node carries `durability_status` as a distinct property from `status`. Two orthogonal questions, two slots.

The fields written match the Phase-1 `Artifact` type contract exactly **plus** the new `durability_status` field this revision adds (this is the load-bearing constraint: the Neo4j node's properties + edges have to project cleanly into a row that round-trips into the `Artifact` shape the cortex-ui store consumes — including the new field).

Specifically:
- `(:AnswerArtifact {id, created_at, updated_at, valid_as_of, valid_until?, question_text, resolved_intent, message_id, status, durability_status, watermark, rendered_output})` — `rendered_output` as inline JSONB property until the size discriminant fires (ADR-0023 leaves this to the implementing PR; this plan ships inline, files a follow-up for the size threshold). **`durability_status` is a property on the node** (not on an edge, not in a JSONB sub-blob) so the projector can query and update it directly. **`watermark` is a property on the node** under Decision 3 Option C — a monotonic int64 assigned at write time, **bumped on every UPDATE** (including updates that only change `status` or `durability_status`). The cortex-bff write helper owns watermark assignment. **`watermark` and `valid_as_of` are orthogonal facts** — `valid_as_of` is the as-of of the grounding (ADR-0023's freshness primitive); `watermark` is the projector's apply-order position (Option C's see-your-write primitive). Two distinct concepts, two distinct slots. Do NOT collapse.
- `(:AnswerArtifact)-[:PRODUCED_BY]->(:Actor {actor_type, actor_id, version?, endpoint?, code_hash?})` — agent identity captured at creation. Refined from the pending-sentinel only if the routing event carries real `handled_by`.
- `(:AnswerArtifact)-[:PRODUCED_FOR]->(:Actor {actor_type, user_id, is_authenticated, user_persona?, entitled_domains?})` — user-side persona slot present even when null (per `[[pingsso-claim-gap]]`).
- `(:AnswerArtifact)-[:DERIVED_FROM]->(:AnswerArtifact)` — when `derived_from_artifact_id` is non-null. (Phase 1 almost always null; the edge-write code path exists for when follow-up detection lands.)
- `(:AnswerArtifact)-[:ROUTED_AS]->(:RoutingDecision {subject_uri, verb_iri, owner_persona, ...})` OR as inline properties on the AnswerArtifact — this hop picks **inline properties** since the first re-use case for a shared RoutingDecision node hasn't fired yet (per ADR-0023's open question). When that case fires, a follow-up migration extracts.
- `(:AnswerArtifact)-[:CITES]->(:Source {uri, type, label})` per source — Source nodes deduped by URN (`MERGE (s:Source {uri: $uri})` semantics), with the per-artifact citation evidence on the `CITES` edge (`{snippet, relevance, open_url}`).

The write is **idempotent** (`MERGE` on `AnswerArtifact.id`), so the pending → complete transition is one Cypher write with property updates, not two creates. Retries of the durability write are also idempotent — re-running the same MERGE against an already-written node is a no-op apart from `updated_at`.

**Durability-status state machine:**

```
Initial: durability_status = "persistence_pending"  (set IMMEDIATELY at delivery time, even if no write attempt has happened yet — honest about the in-flight state)

On successful Neo4j write: durability_status = "durable"

On retryable Neo4j failure (cortex-bff retries within bounded window): durability_status stays "persistence_pending"

On exhausted retries: durability_status = "persistence_failed"
```

The initial `persistence_pending` value is **set in the client-side store at delivery time**, not derived from the absence of a write. This is the load-bearing distinction from naive write-after: the absence of a write is a silent gap; an explicit `persistence_pending` value is honest recorded state. When the Neo4j write succeeds, the projector picks up the `durable` transition and surfaces it through Hop 2/Hop 3 to the client; the client's store transitions from `persistence_pending` (locally set) to `durable` (server-synced).

### Probe shape (predict-before-run)

Hop 1 has **two probes**, both pre-written and both RED-first.

#### Probe 1 — `test_hop1_neo4j_writeback.py` (the happy-path write)

Under `tests/sandbox_e2e/` to mirror existing layout:

```
PRECONDITION: cortex-bff is running, Neo4j is reachable.

GIVEN a known question text "what is engine A's owner_persona for retrieveKnowledge?"
GIVEN a known PRODUCED_FOR actor (test user with stable user_id "test-user-7d")
GIVEN message_id "msg-hop1-001"

WHEN cortex-bff receives the question through its normal entry path
AND the routing decision arrives with verb_iri == "mesh:retrieveKnowledge"
AND stream_end fires
AND the Neo4j write completes (within the bounded retry window)

THEN a (:AnswerArtifact {id: <known-id>, valid_as_of: <committed-timestamp>, durability_status: "durable"}) node exists in Neo4j.
AND (:AnswerArtifact)-[:PRODUCED_FOR]->(:Actor {user_id: "test-user-7d"}) exists.
AND (:AnswerArtifact)-[:PRODUCED_BY]->(:Actor {actor_type: "agent"}) exists with actor_id != "pending"
    (the routing event refined the sentinel).
AND (:AnswerArtifact)-[:CITES]->(:Source) edges resolve to at least one Source node whose uri is non-empty.
AND the (:AnswerArtifact).valid_as_of property is a real epoch-millis number, NOT null, NOT 0.
AND the (:AnswerArtifact).watermark property is a positive int64, NOT null, NOT 0.

ASSERT: a second write with the same id (replay) does NOT create a duplicate node — count of (:AnswerArtifact {id: <known-id>}) == 1.
ASSERT: after the second write, the watermark on the row has STRICTLY ADVANCED (the replay-as-update bumps watermark; vestigial-watermark trap caught).
```

The probe is "predict a specific value AND a specific change-propagation": the predicted value is the question text, the predicted change-propagation is that the pending-sentinel `produced_by.actor_id` got refined to a real engine_name when routing arrived, AND that `durability_status` transitioned from `persistence_pending` (at delivery) to `durable` (after the Neo4j write succeeded), AND that `watermark` advanced on the update (per Decision 3 Option C — every apply that touches the row touches the watermark).

**This probe MUST be able to fail.** Failure modes it has to catch:
- The write never happens (cortex-bff has no Neo4j write path) — the node is absent.
- The write happens but `valid_as_of` is null — capture-or-lose-forever violated.
- The write happens but `durability_status` is missing or still `persistence_pending` — the field isn't being managed, or the success-path transition is broken.
- The write happens but `watermark` is null or 0 — Option C's watermark-as-column wasn't wired.
- The replay-as-update bumps the row but leaves `watermark` unchanged — the vestigial-watermark trap per `[[verify-subtle-acceptance-by-inspection]]`. Every apply that touches the row MUST touch the watermark; if any update path leaves it stale, see-your-write quietly breaks for clients awaiting later writes.
- The write happens but `produced_by.actor_id` is still "pending" — the routing-event refinement path didn't apply.
- The replay creates a duplicate node — idempotency violated.
- The `:Source` node has empty `uri` — `MERGE` keyed on a missing field.

#### Probe 2 — `test_hop1_neo4j_write_failure_honest_state.py` (the decoupling probe — load-bearing)

This is the probe the architect's Decision-0 sub-decision ruling required. It exists specifically to make the decouple-with-honest-failure-state shape **load-bearing instead of optional** — without this probe, an implementer could "implement Hop 1" by just doing the Neo4j write and forgetting the failure-state recording, and the system would silently regress to the dual-write failure mode.

```
PRECONDITION: cortex-bff is running. Neo4j is artificially UNREACHABLE from cortex-bff
              (use a network policy, a deliberately-broken bolt URI, or a Neo4j-pod
              `kubectl scale --replicas=0` for the duration of the probe).

GIVEN a known question text "what is engine A's owner_persona for retrieveKnowledge?"
GIVEN a known PRODUCED_FOR actor (test user with stable user_id "test-user-7d")
GIVEN message_id "msg-hop1-fail-002"

WHEN cortex-bff receives the question through its normal entry path
AND the routing decision arrives
AND stream_end fires
AND the cortex-bff Neo4j-write retry budget is exhausted (Neo4j stays unreachable)

THEN two assertions both hold (a green that asserts only one is HOLLOW):

  ASSERTION A — DELIVERY DECOUPLED:
    The SSE stream completed normally. The client received stream_end. The user
    saw the answer. Neo4j unreachability did NOT cause delivery to fail.

  ASSERTION B — HONEST RECORDED STATE:
    The artifact is in a recorded `delivered-but-persistence-pending` (or, after
    retry exhaustion, `persistence_failed`) state. Specifically:
      - The cortex-ui store has an Artifact row with id=<known-id>, status="complete",
        AND durability_status="persistence_failed" (after retry exhaustion;
        "persistence_pending" if checked mid-retry).
      - The artifact is NOT silently absent (dual-write failure mode).
      - The delivery did NOT fail with an error to the user (coupling mistake).

CLEANUP: restore Neo4j reachability. Confirm that on subsequent retry (if the
implementation supports background reconciliation), the artifact transitions
to durability_status="durable" — OR document that reconciliation lives in
the Restate successor and the persistence_failed state is the terminal interim
state until a manual replay.
```

**Why this probe MUST fail today (the RED-first proof):** there is no `durability_status` concept in the cortex-ui Artifact type today (audit §2.1 confirms the existing field set ends at `status`/`rendered_output`/`produced_by`/`produced_for`/`routing`/`sources`/`graph_trace`/`derived_from_artifact_id`). The probe asserts a value of a field that doesn't exist. Running it against the current sandbox produces a structural failure — the assertion can't even evaluate against the existing schema. **This RED is the proof that the decoupling is real, not "we didn't notice the write failed."** Per `[[pre-written-fixtures-must-fail-first]]`: show RED first, implement the durability-status concept, then run GREEN. A green-without-having-been-red is decorative.

**Why this probe is two-legged (assertions A AND B both required):** a probe that asserts only delivery succeeded (A alone) can pass for the wrong reason: the implementation might be naive write-after with no honest-state recording (delivery passes, the write-failed state is silently dropped). A probe that asserts only honest state (B alone) can pass for the wrong reason: the implementation might be write-before (B passes after a delivery failure that the probe didn't measure). Per `[[fixture-must-exercise-paths]]`, both assertions exercise distinct binding paths the decouple-shape requires. A green that only asserts one leg is hollow.

### Red-first sequence

Both probes pre-written before any Hop 1 code lands. Both must be shown RED first.

1. **Write Probe 1 (happy-path write) first**, against the running sandbox. Run it. **It must fail** — there is no Neo4j write path in cortex-bff today (audit confirms only a `/node_details` reader). The predicted-RED is "no `(:AnswerArtifact {id: <known-id>})` exists." Inspect the failure message; confirm it's the predicted-RED and not e.g. a Neo4j connection error.
2. **Write Probe 2 (write-failure-honest-state) next**, against the same sandbox. Run it. **It must fail differently than Probe 1** — Probe 2's failure is structural: the `durability_status` field doesn't exist in the Artifact schema yet, so the probe's assertion against that field can't evaluate. Predicted-RED is "field `durability_status` not present in Artifact / Neo4j node." This RED is the proof that the decouple-with-honest-failure-state shape is being added net-new; if Probe 2 went green initially, the assertion is trivially-true and decorative.
3. **Add the `durability_status` field to the AnswerArtifact model** — cortex-ui type (`src/api/types.ts`), Neo4j schema (just a property name; no migration), cortex-bff write helper. **Do NOT collapse `durability_status` into `status`** — they are orthogonal per the architect's ruling and `[[verify-subtle-acceptance-by-inspection]]`.
4. **Add the Neo4j write helper to cortex-bff.** Idempotent MERGE patterns. PRODUCED_FOR/PRODUCED_BY/CITES edge writes. Bounded-retry loop. On success → set `durability_status = "durable"`. On exhausted retries → set `durability_status = "persistence_failed"` in the local store and surface it through the store path.
5. **Hook the SSE event handlers in cortex-bff.** Delivery at `stream_end` is independent of the Neo4j write per the architect's ruling. The write attempt runs on its own track; it does NOT gate delivery. The initial `durability_status = "persistence_pending"` is set at delivery time in the store; the write attempt drives it forward.
6. **Re-run Probe 1.** Expect GREEN. Inspect: open Neo4j browser, confirm by eye the node + edges shape match the predicted property names, including `durability_status = "durable"`.
7. **Re-run Probe 2.** Expect GREEN — but only if BOTH assertions A and B hold. Specifically with Neo4j made unreachable, delivery still completes AND the artifact carries `durability_status = "persistence_failed"` after retry exhaustion. If only A passes, the implementation regressed to fire-and-forget. If only B passes, delivery is still coupled. A one-legged green is hollow.

### Breakpoint

Hop 1 is done when:
- **Probe 1 is green AND was red before the implementation landed.**
- **Probe 2 is green AND was red before the implementation landed AND both legs (delivery decoupled + honest recorded state) are independently asserted in the green run.**
- A second variant of Probe 1 — re-run the same question with a fresh `id`, then re-run AGAIN with the SAME `id` — shows idempotency (count == 1).
- An inspector check on a real Neo4j browser session confirms the node has `valid_as_of` populated AND `durability_status` populated, and the edges resolve to the expected target labels.
- The Artifact type in `cortex-ui/src/api/types.ts` has a new `durability_status` field. This is the first deliberate Artifact type change since Phase 1 — it surfaces in the Hop 3 byte-identical-diff probe (which will now diff against a post-Hop-1 baseline, not against the pre-Hop-1 commit). The architect signs off on the Artifact type addition when Hop 1 closes; that sign-off is the new baseline for Hop 3's diff probe.
- The Hop 2 probe (next section) has been WRITTEN but not yet run. The build session is about to open Hop 2.

## 5. Hop 2 plan — the projector, Neo4j → Postgres

### Scope

Stand up the projector: a new `iagent-projector` Deployment (Decision #4), polling Neo4j on a 500ms interval against an `updated_at` cursor (Decision #1), upserting into the `answer_artifact_projection` table on Postgres (Decision #2), and advancing the `projector_watermark` row (Decision #3).

Schema migrations land in this hop:
- `CREATE INDEX ON :AnswerArtifact(updated_at)` on Neo4j (required for poll efficiency).
- `CREATE TABLE answer_artifact_projection (id text PRIMARY KEY, kind text NOT NULL DEFAULT 'AnswerArtifact', created_at bigint, updated_at bigint, valid_as_of bigint NOT NULL, valid_until bigint, question_text text, resolved_intent jsonb, message_id text, status text, durability_status text, rendered_output jsonb, produced_by jsonb, produced_for jsonb, routing jsonb, sources jsonb, graph_trace jsonb, derived_from_artifact_id text, watermark bigint NOT NULL)`. **`durability_status` is a separate top-level column from `status`** (not a JSONB sub-field — consumers filter by it). **`watermark` is a top-level column under Decision 3 Option C** — bumped on every apply, including durability-only or status-only changes. Two top-level columns (`durability_status`, `watermark`) — both orthogonal to `status` for different reasons; do not collapse either.
- **~~`CREATE TABLE projector_watermark`~~ — DELETED under Decision 3 Option C.** The original synced single-row watermark table is dead. The watermark lives only as a column on the artifact row.
- `CREATE TABLE projector_cursor (id int PRIMARY KEY DEFAULT 1, last_polled_updated_at bigint NOT NULL, last_applied_watermark bigint NOT NULL DEFAULT 0)` — projector's own resumable state. **The `last_applied_watermark` field is added under Option C** so the liveness probe (Decision 4, revised) can read the projector's internal cursor without depending on a synced row. It is INTERNAL state, NOT synced to Electric.

The projector's apply loop: poll Neo4j → assemble the projected row (denormalizing edges into the JSONB columns; copying `durability_status` and `watermark` as top-level columns) → upsert into `answer_artifact_projection` (the watermark column carries the per-row position; every apply bumps it including no-content changes that only touch status or durability_status) → update `projector_cursor.last_applied_watermark` to the newly-applied value → advance the poll cursor. **No separate watermark-row write.** The `GET /projector/watermark` HTTP endpoint reads `projector_cursor.last_applied_watermark` (or the in-process counter that mirrors it) for probe/admin/operability use.

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
AND the row's watermark column is > 0 (Option C: the watermark is on the row itself)
AND projector_cursor.last_applied_watermark >= the row's watermark (internal cursor advanced to match)

PHASE B — update propagation (THE DISCRIMINATING TEST):
GIVEN the projected row from Phase A exists with status == 'complete' and watermark == <W_A>
WHEN cortex-bff issues an updateArtifact equivalent that sets status to 'failed' AND bumps watermark to <W_B> where W_B > W_A
AND the Neo4j AnswerArtifact's status property is set to 'failed' (the write commits, watermark bumped)
AND the projector's next apply cycle fires (≤ 1.5s wait)

THEN the row in answer_artifact_projection has status == 'failed'
AND the row's updated_at is greater than its value pre-update
AND the row's watermark column == <W_B> (advanced; Option C requires every apply to copy the new watermark)
AND projector_cursor.last_applied_watermark >= <W_B>

PHASE C — idempotent replay (poll without changes):
GIVEN the Neo4j AnswerArtifact has not changed
WHEN three consecutive polls fire
THEN the row in answer_artifact_projection is unchanged across the three polls (same updated_at, same watermark column)
AND projector_cursor.last_applied_watermark does NOT advance when there are no real applies (NOT every poll bumps it)

PHASE D — durability_status orthogonal propagation AND watermark-advanced co-required (EXPANDED under Decision 3 Option C):
GIVEN a Neo4j AnswerArtifact exists with status='complete' AND durability_status='persistence_pending' AND watermark=<W0>
      (the post-delivery, mid-retry state from Hop 1's decoupled write path)
WHEN cortex-bff's retry succeeds and patches the node to durability_status='durable' AND bumps watermark to <W1> where W1 > W0
AND the projector's next apply cycle fires (≤ 1.5s wait)
THEN the row in answer_artifact_projection has durability_status='durable'
AND the row's status is STILL 'complete' (the two fields are orthogonal; the projector did NOT collapse them)
AND the row's watermark column == <W1> (advanced; NOT vestigial)
AND projector_cursor.last_applied_watermark >= <W1>

CONVERSE 1 (durability_status alone, status unchanged — orthogonality leg):
GIVEN a Neo4j AnswerArtifact exists with status='complete' AND durability_status='persistence_pending' AND watermark=<W0>
WHEN cortex-bff's retry budget exhausts and patches the node to durability_status='persistence_failed' AND bumps watermark to <W2> where W2 > W0
AND the projector's next apply cycle fires
THEN the row has durability_status='persistence_failed' AND status STILL 'complete' AND watermark=<W2>.

CONVERSE 2 (watermark-advanced co-required leg — the EXPANSION under Option C):
GIVEN a Neo4j AnswerArtifact exists with status='complete' AND durability_status='persistence_pending' AND watermark=<W0>
WHEN cortex-bff's retry succeeds and patches durability_status='durable' AND ALSO bumps watermark to <W3>
AND the projector applies
THEN the row's watermark column is STRICTLY <W3>, not <W0>.
ASSERT FAILURE MODE: if the projector applies the durability_status change but does NOT copy the new watermark (e.g., because the projector's update path branches on status changes and only reads watermark from there), this probe goes RED. That's the vestigial-watermark trap and it must be caught.
```

**Phase B is the load-bearing test for update propagation.** Insert-only projectors are easy to write; update-respecting projectors are where the rot lives. The probe MUST fail if the projector treats updates as inserts (duplicates), if it ignores updates (stale rows), or if it advances the watermark on every poll regardless of change.

**Phase D is doubly load-bearing under Decision 3 Option C.** Per `[[verify-subtle-acceptance-by-inspection]]`, the temptation when implementing the projector is to fold `durability_status` into the `status` JSONB or to overload `status` itself; the original probe shape catches that. **The Option-C expansion catches a sibling trap one layer over**: an update path that bumps the row but quietly fails to copy the new watermark. Per `[[fixture-must-exercise-paths]]`, Phase D MUST exercise the durability-only update path (not just status updates) — a fixture that only exercises status updates leaves the durability-only-but-watermark-doesn't-bump trap invisible. The two assertions are **co-required**: durability_status propagates orthogonally AND watermark advanced on the durability-only change. A green that asserts only one is hollow for the same reason a one-legged Hop 1 Probe 2 green is hollow.

**Why this matters under Option C specifically.** With the original synced-watermark-row design, the watermark advancement was a single explicit write the projector did after the artifact upsert; it was hard to forget. Under Option C, the watermark IS a field on the artifact row, which means the projector's update logic might branch on "what changed" and accidentally skip the watermark on durability-only changes (because the code path "an update is propagating a status field" doesn't realize the watermark column also has to advance). The expanded Phase D forces every update path through the watermark column. Without it, Option C's see-your-write quietly breaks for any client awaiting a later write — `max(watermark)` could be satisfied by a stale max, OR the updated row's unchanged watermark could make the client's await-logic reason against the wrong position.

### Red-first sequence

1. **Write the probe against a sandbox where Hop 1 is green but no projector exists.** Run it. **Phase A must fail** with "row not found in `answer_artifact_projection`" (the table doesn't even exist, or the projector isn't applying). Predicted-RED. Confirm.
2. Run the schema migrations on Postgres. Deploy the projector (Deployment template added to helm).
3. Re-run Phase A. Expect GREEN.
4. With the projector running, simulate the update in Phase B (deliberately patch the Neo4j node to set `status = 'failed'`). Re-run the probe — Phase B has never run on the new projector. **Predict: GREEN if updates apply; RED if the projector only inserts.** Inspect either outcome carefully. (This is the moment where many projector implementations silently fail — the implementation might have "looked complete" after Phase A passed.)
5. Phase C is a stability check; run after A and B are both green. Predicted GREEN if watermark advancement is change-gated.
6. **Phase D — durability_status orthogonality AND watermark-advanced co-required.** Patch the Neo4j node to change `durability_status` AND bump `watermark` while leaving `status` unchanged. Re-run the probe. **Predict: GREEN if the projector propagates both the durability_status change AND the new watermark column value; RED if the projector collapsed durability_status into status, OR if the projector applied the update but copied the OLD watermark (the vestigial-watermark trap).** Run the CONVERSE 1 (durability_status alone) case AND CONVERSE 2 (watermark-advanced co-required) case explicitly. Per `[[verify-subtle-acceptance-by-inspection]]`, inspect the projected row's column-level state — specifically read the watermark column, don't just trust the assertion result. Per `[[fixture-must-exercise-paths]]`, the fixture must exercise the durability-only update path (not piggyback on status updates); a fixture that only exercises status updates leaves the trap invisible.

### Breakpoint

Hop 2 is done when:
- All four phases are green, and Phases A, B, and D were red before the projector code landed.
- The Hop 3 byte-identical-diff probe (next section) has been WRITTEN but not yet run.
- A short observability check: `kubectl logs deployment/iagent-projector --tail=50` shows the apply loop is alive and advancing the internal cursor. A stuck loop is the projector's quiet-failure mode; the operator has to be able to see it from logs. Per `[[liveness-probe-watches-advance-not-just-correctness]]`, the advance-check liveness probe — now reading `projector_cursor.last_applied_watermark` via `GET /projector/watermark` (Decision 4's revised internal-cursor source under Option C, NOT a synced row that no longer exists) — verified can-fail by killing the apply loop and watching it go red.
- A column-level audit of `answer_artifact_projection`: every row has a non-zero `watermark`, and the column is strictly monotonic across the apply history. If any row has watermark=0 or a non-monotonic value, the projector's watermark-management is broken and Hop 2 is NOT done.

## 6. Hop 3 plan — Postgres → Electric → store

### Scope

Stand up the Electric server (`iagent-electric` Deployment + Service). Configure a single Shape that selects `answer_artifact_projection` rows scoped by the requesting user's `produced_for.user_id` (so the canvas only syncs that user's artifacts — privacy-preserving by construction). Add the Electric client subscription to `cortex-ui` that drives `useCanvasStore` from the synced rows.

Critical constraint: **the `Artifact` type contract in `c:/Users/cnogr/git/cortex-ui/src/api/types.ts` does NOT change.** The Electric-synced row maps 1:1 onto the existing `Artifact` shape. The `useInterviewAgent` mock-fed path either stops being the source of truth (preferred) or remains as a fast-path for the immediate-create-pending step while Electric drives the durable updates (acceptable interim).

### Probe shape

`test_hop3_electric_to_store_diff.py` is a **two-part probe**.

**Part 1 — byte-identical type contract (baseline = post-Hop-1, with `durability_status` AND `watermark` added):**

```
GIVEN c:/Users/cnogr/git/cortex-ui/src/api/types.ts as of the post-Hop-1 commit, AFTER the architect-approved
      additions of:
        (a) the `durability_status` field (Decision 0 sub-decision ruling, revision 2 of this plan), AND
        (b) the `watermark: number` field (Decision 3 Option C, revision 3 of this plan)
      but BEFORE any Hop 3 changes.
      (This is a TWICE-SHIFTED baseline relative to the original draft: revision 1 pinned the baseline at
      the pre-Hop-1 commit; revision 2 shifted it for `durability_status`; revision 3 shifts it again
      for `watermark`. The architect's sign-off at Hop 1's breakpoint is what establishes the new baseline —
      the two additions are bundled into Hop 1 because they're orthogonal slot-additions in the same
      foundation work, not because they share a concept.)
WHEN Hop 3's swap lands
THEN git diff between the post-Hop-1 baseline and the post-Hop-3 commit on src/api/types.ts is EMPTY
     for the Artifact interface block (lines covering the Artifact interface).

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
- Part 1 diff probe is GREEN at the end (after the swap) — the Artifact type didn't drift relative to the post-Hop-1 baseline (which includes both `durability_status` and `watermark`).
- Part 2 propagation probe is GREEN AND was red before the swap.
- **Part 3 DROPPED under Decision 3 Option C.** Recorded explicitly here so a future reader doesn't read "two probes" as "Part 3 is missing." The see-your-write ordering invariant is **dissolved** by Option C — there are no longer two things to deliver in order, so there is no ordering contract left to probe. "No probe needed" is the correct outcome here, not a missing probe. The spike `fe14d67` + Option C ruling did not just satisfy the see-your-write test; it made the test inapplicable. See Decision 3 in §3 for the architect's structural-vs-coordinated reasoning verbatim.
- A manual canvas check: type a query in the running cortex-ui, watch the pending → complete transition, watch the Sources card populate with a URN that matches `subtask_routing_decision`'s `subject_uri` in the corresponding Dagster run. This is the Monday-handoff visual proof.
- A see-your-write smoke check (NOT a probe — the contract is structural now, no probe is required): write an artifact, immediately read `useCurrentArtifact()`, confirm it's there. If it's NOT there, something violated Option C's invariant (likely the watermark column isn't being copied on the artifact apply, or Electric isn't subscribed correctly). Diagnose by inspecting the artifact row in Postgres directly.
- Optional but recommended: shut down the SSE path entirely for one test session and confirm the canvas still works end-to-end via Electric alone. (If it doesn't, the SSE path is still load-bearing and the swap is incomplete.)

## 7. Cross-cutting discipline

These rules apply across all three hops. Each hop's plan references them above; this section makes them load-bearing in one place.

- **Integration probe per contract, each able to fail.** Per `[[feedback-endpoint-probe-per-engine]]` and `[[feedback-verification-must-fail]]`: every hop's probe predicts a SPECIFIC value AND a SPECIFIC change-propagation. A probe that returns "all green" because the readback cache stayed warm, or because the projected row was the mock all along, is the always-green anti-pattern this stack now codifies as a recognized class. The Phase B "update propagation" assertion in Hop 2's probe is the canonical instance: insert-only projectors look complete until update arrives.

- **Pre-written fixtures must fail first.** Per `[[pre-written-fixtures-must-fail-first]]`: each hop's probe is written BEFORE the hop's code, and is shown FAILING before the hop's code lands. The red-green transition is the proof. Specifically:
  - Hop 1: BOTH probes written and RED first. Probe 1's predicted-RED is "no AnswerArtifact node in Neo4j" — confirm RED before adding the cortex-bff Neo4j writer. Probe 2's predicted-RED is structural: "field `durability_status` doesn't exist in the Artifact / Neo4j node schema" — confirm RED before the durability_status concept is added. Both legs of Probe 2 (delivery decoupled + honest recorded state) asserted in the green run; a one-legged green is hollow.
  - Hop 2: probe written, Phase A predicted-RED is "row not in answer_artifact_projection" — confirm RED before deploying the projector. Phase B's update-propagation must ALSO go red before code, NOT just degenerate-green by accident of the insert path. Phase D's expanded both-legged assertion (durability_status orthogonal propagation AND watermark-advanced co-required) must go red before code — predicted-RED is either "durability_status column doesn't exist in the projection," or "the projector overloaded durability_status onto status," or "the projector applied the durability change but copied the OLD watermark." Per `[[fixture-must-exercise-paths]]`, the fixture must EXERCISE the durability-only update path; a fixture that only exercises status-updates leaves the watermark-doesn't-bump trap invisible. **The projector's liveness probe is itself subject to this rule** — kill the apply loop, watch the liveness probe (now reading `projector_cursor.last_applied_watermark` via `GET /projector/watermark` per Decision 4's Option-C-revised internal-cursor source) go red, then trust green afterward.
  - Hop 3: byte-identical-diff probe is degenerate-green pre-swap (with the baseline twice-shifted to post-Hop-1, which includes both `durability_status` and `watermark` field additions); Part 2 must go RED before Electric is deployed. **Part 3 (see-your-write ordering probe) DROPPED under Decision 3 Option C.** No ordering invariant exists; no probe is required. This is the correct outcome, not a missing probe — recorded explicitly so a future reader does not misread it.

- **Liveness watches advance, not just correctness.** Per `[[liveness-probe-watches-advance-not-just-correctness]]` (banked from this plan's original §7 footnote, elevated by the architect): the projector's liveness check asserts the loop is ADVANCING — `projector_cursor.last_applied_watermark` increments (the internal-cursor source under Option C, exposed via `GET /projector/watermark` for probes and admin) — not just that data is currently correct. Frozen-but-correct is the failure mode a correctness-only probe misses. A stopped projector with a backfilled-once table is data-identical to a healthy projector; only the advance check distinguishes them. **Under Option C the advance signal lives in the projector's own internal state, NOT in a synced row** — arguably cleaner, because the liveness signal should come from the loop's own state, not from a row it writes.

- **Coupled interim mechanisms retire together.** Per `[[coupled-interim-mechanisms-retire-together]]` (banked from this plan's Decision-1/Decision-3 coupling; this plan is the first instance): the interim trio of Decisions 0, 1, and 3 retires together under the Restate+topic successor. The retirements share a single cause (no streaming change-feed today); they exit together when that cause is removed. **The Option C watermark COLUMN is NOT permanent substrate even though it survives Hop 2** — when the Restate+topic successor lands, the topic offset becomes the projector's position and the per-row watermark column becomes redundant scaffolding. Its retirement is documented in §3.5's Through-line table.

- **Ordering questions hide coupling questions.** Per `[[ordering-questions-hide-coupling-questions]]` (banked from this plan's Decision-0 sub-decision; this plan is the first instance): when a sub-decision is framed as "in what order do these two operations against two systems happen?", STOP and check whether they should be ordered at all. "Before vs after" presupposes a coupled sequence, which is the dual-write failure shape one layer down. The right answer is usually decouple-with-honest-failure-state per-domain. This plan's Decision-0 sub-decision is the canonical case; the rule will fire again in ADR-0024 Part B's publish-backend planning (publish action ordering, scrub ordering, SUPERSEDES chain construction) per the memory's "Where this rule was about to apply" section. Sibling rule to `[[coupled-interim-mechanisms-retire-together]]` at a different layer — both detect coupling-the-planner-missed; one fires on decisions, the other on operations.

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

## 10. STOP for this thread (TRULY FINAL — build session opens with a separate agent)

**This revision-3 commit is the TRULY FINAL STOP point for the planning thread.** Binding. The architect signs off the moment this commit lands. The next thread is **Hop 1 with a separate build agent** — not me — proceeding directly to the cortex-bff Neo4j write authority work. Gates 1 (Neo4j edition) and 2 (Electric-position spike) are CLOSED in this revision.

Prior commits in the audit trail:
- `ded7cc7` — original draft (four decisions, four hops).
- `07023ce` — revision 1 (Decision 0 elevated, Decisions 1 + 3 reframed as coupled interim-with-named-successor, build-sequencing gates added).
- `0c2f5fe` — revision 2 (Decision 0 sub-decision settled with decouple-with-honest-failure-state, `durability_status` introduced as a new field distinct from `status`, Hop 1 gains the `@neo4j-write-failure-honest-state` probe, `[[ordering-questions-hide-coupling-questions]]` cited).
- this commit — revision 3 (Decision 3 RESOLVED Option C by spike `fe14d67` + architect ruling: watermark is a COLUMN on every artifact row, not a synced row, not a separate shape. Hop 3 Part 3 DROPS — ordering invariant dissolved. Decision 4 liveness probe revised to read internal cursor. Hop 2 Phase D EXPANDED with co-required watermark-advanced assertion. Schema reflects column-not-row.).

The five primary decisions are settled:
- **Decision 0** (cortex-bff as write authority) with sub-decision (decouple-with-honest-failure-state, continuity-to-Restate-successor proven).
- **Decision 1** (poll-as-interim, Restate+topic successor named) — coupled with 0 and 3 in retirement.
- **Decision 2** (wide table + discriminator) — PERMANENT.
- **Decision 3** RESOLVED (Option C, watermark-as-column on every row) by spike + ruling — interim, retires with 0 and 1 under the Restate+topic successor.
- **Decision 4** (separate Deployments, internal-cursor liveness under Option C) — PERMANENT with one Option-C-driven probe-source adjustment.

The fixture discipline is settled (RED-first per pre-written rule, both legs of two-legged probes asserted, advance-check liveness reading internal cursor, orthogonality on durability_status AND watermark-advanced co-required at every apply). The build-session sequencing is settled and locked: gates 1 and 2 CLOSED; build proceeds at gate 3 (Hop 1) → gate 4 (Hop 2) → gate 5 (Hop 3) → gate 6 (visual confirmation).

This thread does NOT:
- Write backend code (no Neo4j writer in cortex-bff, no projector Deployment, no Electric Shape).
- Modify any helm chart (no new templates, no values changes).
- Write to any database (Neo4j read-only via inspector existing today; Postgres untouched).
- Change the cortex-ui Artifact type (zero diff against `src/api/types.ts` — `durability_status` AND `watermark` field additions are planned for Hop 1 of the build session, not implemented here).
- Run the Electric-native-position spike (the spike `fe14d67` already ran and informed Decision 3's Option C resolution; no re-run is needed).
- Open the build session for the next agent (the dispatch happens after this commit).

The build session is the next thread, opening with a separate build agent the moment the architect signs off on this commit. The Hop 1 dispatch references this committed plan. My job ends at this commit.

If, in the moments after this commit, the pull arrives to "just sketch hop 1's Neo4j write while I'm in here" — STOP. The build agent is the one who does Hop 1, not me. Skipping the handoff would collapse the planning/build separation that has been the load-bearing discipline of this entire thread.
