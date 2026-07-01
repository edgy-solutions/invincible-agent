# invincible-agent helm chart — changelog

## 0.2.0 — 2026-06-30

Minor bump. Two behavior changes worth flagging for operators; four
correctness fixes that had accumulated without a version bump.

### Behavior changes (opt-out possible but not default)

- **Per-user artifact isolation via cortex-bff Electric proxy.** The
  cortex-ui browser client no longer connects to Electric directly.
  All shape subscriptions flow through `cortex-bff /electric/shape`,
  which validates the JWT, extracts `sub`, and injects a
  server-verified `WHERE produced_for_user_id = '<sub>'` into every
  upstream Electric shape request. Each authenticated user sees only
  their own artifacts. Not access control — that's the ADR-0025 arc;
  this is under-share-by-ownership as a demo-safe interim.
  - Requires Keycloak users to have distinct `sub` values. The
    seeded `agent-user` account remains; three demo tester accounts
    (`alice`, `bob`, `carol` — passwords match usernames) added.
  - New Postgres column `produced_for_user_id TEXT` on
    `answer_artifact_projection` (regular column, populated by the
    projector on every INSERT/UPDATE). Migration is idempotent
    `ADD COLUMN IF NOT EXISTS` in
    `sql/create_answer_artifact_projection.sql`.

- **Direct Electric ingress closed.** The public
  `electric.edgy-solutions.com` ingress is removed
  (`values-sandbox.yaml: electric.ingress.enabled=false`). Exposing
  Electric directly would let a browser bypass the proxy with a
  self-supplied `where` clause. In-cluster Electric service is
  unchanged; cortex-bff reaches it via the DNS name
  `iagent-electric:3000` (env `ELECTRIC_UPSTREAM_URL`).

### Correctness fixes (were latent but not previously chart-bumped)

- **AnswerArtifact `graph_trace` now persists through Hop 1 + Hop 2.**
  The writer's Cypher MERGE was missing
  `a.graph_trace_json = $graph_trace_json`; the projector was
  hardcoded to `graph_trace = []`. Pre-Hop-3, the cortex-ui SSE
  handler shoved trace nodes directly into the canvas store, so the
  Detailed-HUD's Subject Graph card rendered even though the
  substrate path was broken. Hop 3 cut the SSE handler off and made
  Electric sole-source; the card silently disappeared. Both halves
  fixed; the card renders again for Engine W routes.

- **Engine W sources_collected survives Restate replay.** The
  smolagent's `sources_collected` was a closure variable mutated
  inside `ctx.run("run-smolagent", ...)`. On journal replay, cached
  ctx.run result returned without re-executing the function; closure
  mutations didn't replay; the response ended up with `sources: []`.
  Fixed by returning `{agent_response, sources}` from run_smolagent
  as a single dict that Restate journal-captures.

- **Engine W's BAML editor no longer narrates figure availability.**
  Rules 3+4 added to `FormatKnowledgeResponse` explicitly forbid
  paraphrasing "available via structural panel links" / "not
  rendered inline" / "accessed through the source system." Figure
  placement is the renderer's job, not the LLM's.

- **cortex-bff `/electric/shape` proxy** — strips client-supplied
  `where`, injects verified user_id, forwards Electric protocol
  headers (`electric-handle`, `electric-offset`, `electric-up-to-date`,
  `electric-schema`, `electric-cursor`) via CORS
  `expose_headers` so ShapeStream's incremental sync works.

### Chart mechanics

- `appVersion` updated to `2026.06.30` (previously `"0.1.1"`, which
  was stale and caused the projector template's default tag fallback
  to point at a non-existent GHCR tag when `projector.image.tag` was
  empty; that's fixed independently in `values.yaml` where the
  projector now pins `tag: "latest"` explicitly).

## 0.1.32 through 0.1.41 — pre-per-user-isolation

See git log; no CHANGELOG was maintained in this range. Highlights:

- 0.1.41 — LiteLLM env / envFromSecrets / envFromConfigMaps
- 0.1.40 — LiteLLM api_key on every model_list entry
- 0.1.39 and earlier — LiteLLM chart, doc-tools code-location,
  DataHub sensor, Restate service, etc. Bumps came in bursts;
  not every substantive change bumped.
