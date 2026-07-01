# invincible-agent helm chart — changelog

## 0.2.3 — 2026-07-01

Patch bump. Electric image now honors `global.imageRegistry` /
per-component `registry` overrides.

### Chart mechanics

- **Electric template refactored to use `invincible-agent.image`
  helper.** Previously the image line was a direct-string
  concatenation (`{{ .Values.electric.image.repository }}:{{ tag }}`),
  which meant `global.imageRegistry` didn't apply. Private-registry
  deploys had to bake the registry into `repository`, e.g.
  `repository: "artifactory.corp.example.com/electricsql/electric"`.
- Now uses the same helper that dagster, projector, cortex-bff,
  cortex-ui, etc. use:
    ```yaml
    # Option A: consolidate under global
    global:
      imageRegistry: "artifactory.corp.example.com"
    electric:
      image:
        registry: ""      # explicit clear so global wins

    # Option B: per-component
    electric:
      image:
        registry: "artifactory.corp.example.com"
    ```
- Default in values.yaml pins `registry: "docker.io"` explicitly so
  the shipped default still renders `docker.io/electricsql/electric:1.0.13`
  for stock deploys.

Postgres + user-deployments (pub-tools / dag-tools images) still
use the direct-string shape — a separate refactor. Their overlays
still work via the bake-into-repository pattern.

## 0.2.2 — 2026-07-01

Patch bump. Per-pod toggles for user-deployments.

### Behavior

- **User-deployment code-location and broker are now independently
  togglable.** Previously `userDeployments.<name>.enabled: true`
  always rendered both the Dagster code-location pod AND the mesh
  broker pod as a fixed pair. Some deploys want only one:
    - broker-only: URN resolution works, no local materializations
      (assets live on another Dagster instance)
    - code-location-only: assets materialize via the daemon, but the
      mesh doesn't know about them (integration testing, hidden
      internal pipeline)
  Override:
    ```yaml
    userDeployments:
      pub-tools:
        enabled: true
        codeLocation:
          enabled: false   # skip the code-location pod
        broker:
          enabled: true    # broker still runs
    ```
  Backward compat: existing overlays that don't set the per-pod
  `enabled` keep rendering both pods.

## 0.2.1 — 2026-07-01

Patch bump. Pull for private-registry deploys that need the new
`mc` image path.

### Chart mechanics

- **`mc` image consolidated under `global.images.mc`.** Follows the
  same override pattern operators already use for `global.images.curl`
  and `global.images.postgresClient`. One place to redirect utility
  images at your artifactory for private-registry deploys.
    ```yaml
    global:
      images:
        mc: "artifactory.corp.example.com/minio/mc:RELEASE.2025-08-13T08-35-41Z"
    ```
  Legacy `.Values.minioBucketInit.image` still falls back gracefully;
  no forced overlay migration.

- **`minio/mc` added to `scripts/mirror-to-artifactory.ps1`.** Private
  registries that mirror via that script now get `mc` pulled alongside
  `minio/minio`. Pinned to `RELEASE.2025-08-13T08-35-41Z` for
  reproducibility (was implicitly `:latest`).

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
