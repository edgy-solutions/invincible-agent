# invincible-agent helm chart — changelog

## 0.3.4 — 2026-07-01

Patch bump. Fixes chart-package silent-empty SQL bug that was making
0.3.2 and 0.3.3 look like the wrong fix.

### Fix

- **`db-configmap.yaml` reads SQL from `files/sql/` (chart-relative),
  not from `sql/` (repo root).** Helm's `.Files.Get` cannot reach
  files outside the chart directory. The previous templates
  referenced `.Files.Get "sql/create_bpmn_catalog.sql"` — outside
  the chart — so `.Files.Get` silently returned `""` and the
  ConfigMap shipped with EMPTY SQL fields. The db-init hook then
  ran `psql -f` on empty files (exit 0, no output, no CREATE
  TABLE), silently completed, helm reported "hook succeeded," and
  every fresh install ended up with NO tables.
- Symptom the architect finally caught by watching the pod live:
    ```
    Applying BPMN catalog schema (as postgres superuser)...
    Applying projector schema ...
    Granting runtime privileges to app user 'iagent'...
    GRANT
    GRANT
    ...
    DB init complete.
    ```
  The GRANT block ran (its SQL is inline in the shell script). The
  two `psql -f` commands printed NOTHING because the SQL files were
  empty — no `CREATE TABLE`, no `NOTICE relation ... already
  exists`, nothing.
- Sandbox happened to work because someone applied the SQL manually
  during Hop 2 rollout (the tables have been there since); every
  fresh install elsewhere has been broken since day one.
- Fix: chart-scoped `helm/invincible-agent/files/sql/` is now the
  authoritative source. Repo-root `sql/` stays for manual `psql`
  reference and dev use. Both are kept in sync manually until a
  future consolidation.

## 0.3.3 — 2026-07-01

Patch bump. Fixes db-init on PG15+ / PG17 (Bitnami-flavored deploys).

### Fix

- **db-init hook connects as `postgres` superuser** for schema apply.
  PG15+ removed the default `PUBLIC → CREATE` grant on the `public`
  schema. Even a database OWNER (which Bitnami's `POSTGRESQL_USERNAME`
  becomes for its `POSTGRESQL_DATABASE`) can't `CREATE TABLE` in
  public without an explicit grant. PG17 continues that posture.
  Symptom on fresh Bitnami PG17 deploys: `helm upgrade` reports
  "Upgrade complete" but tables are silently missing; cortex-bff /
  projector then crash on first request with `relation "bpmn_catalog"
  does not exist` / `relation "projector_cursor" does not exist`.
- Fix: hook now uses `PGUSER=postgres` + password from
  `postgresql.auth.postgresPassword` (falls back to `.auth.password`
  for the Docker-library image where POSTGRES_USER IS a superuser).
  Schema DDL is privileged; superuser is the right actor.
- Then grants runtime privileges to the app user so cortex-bff /
  engine-a / projector can INSERT/UPDATE/DELETE:
    ```sql
    GRANT USAGE ON SCHEMA public TO iagent;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES ...;
    GRANT USAGE, SELECT ON ALL SEQUENCES ...;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ... TO iagent;
    ```
  `ALTER DEFAULT PRIVILEGES` covers tables created LATER by future
  schema migrations without needing to re-grant each time.
- Docker library postgres deploys are unaffected — its `POSTGRES_USER`
  is implicit superuser so grants are no-ops but harmless.

## 0.3.2 — 2026-07-01

Patch bump. Fixes a latent-since-Hop-2 schema migration gap.

### Fix

- **`db-init` helm hook now applies BOTH schemas** — bpmn_catalog AND
  the projector's answer_artifact_projection + projector_cursor +
  projector_skip_log. Previously only bpmn was applied; the projector
  template comment falsely claimed the projector "applies
  sql/create_answer_artifact_projection.sql idempotently on startup"
  but the code never did — it only READS `projector_cursor` and
  hard-fails if the row is missing. Fresh installs (including the
  work Bitnami deploy 2026-07-01) crashed with:
    - `relation "bpmn_catalog" does not exist` (cortex-bff)
    - `relation "projector_cursor" does not exist` (projector)
- Both schemas use `CREATE TABLE IF NOT EXISTS` — safe to re-run on
  every helm upgrade.
- Added `psql -v ON_ERROR_STOP=1` + `set -e` so a schema-apply
  failure fails the hook loudly instead of silently continuing.
- Projector template comment corrected to describe reality.

## 0.3.1 — 2026-07-01

Patch bump. Electric now works against Bitnami Postgres out of the box.

### Fix

- **Electric pod gets an `initContainer` that grants REPLICATION to
  the connection role.** Root cause: Bitnami's `POSTGRESQL_USERNAME`
  creates a NON-superuser role by default, so `iagent` couldn't
  create logical replication slots. Electric crashed with
  `FATAL 42501 (insufficient_privilege) permission denied to start
  WAL sender`. The official `postgres` image happens to make its
  `POSTGRES_USER` a superuser (REPLICATION implicit), so this bug
  only surfaced on Bitnami.
- Fix: `grant-replication` initContainer connects as the `postgres`
  superuser (using `POSTGRESQL_POSTGRES_PASSWORD` on Bitnami, or the
  same as the app password on the official image where user IS
  superuser) and issues `ALTER ROLE <app-user> WITH REPLICATION`.
  Idempotent — subsequent boots re-run the ALTER as a no-op.

## 0.3.0 — 2026-07-01

**Minor bump. Overlay migration required for private-registry deploys.**

Every third-party image reference now flows through the
`invincible-agent.image` helper. Single override point:
`global.imageRegistry` redirects everything (or override per-image
via `<component>.image.registry`). The `global.images.*` map (curl,
mc, postgresClient) is retired in favor of top-level `utilImages.*`
with the same registry/repository/tag shape.

### Overlay migration guide

**Before (0.2.x)**:

```yaml
global:
  images:
    curl: "artifactory.corp.example.com/curlimages/curl:latest"
    mc: "artifactory.corp.example.com/minio/mc:RELEASE.2025-08-13T08-35-41Z"
    postgresClient: "artifactory.corp.example.com/postgres:15-alpine"

# and every third-party component needed the registry baked in
postgresql:
  image:
    repository: "artifactory.corp.example.com/library/postgres"
    tag: "16"
neo4j:
  image:
    repository: "artifactory.corp.example.com/library/neo4j"
    tag: "5.26.0"
# ... etc for weaviate, fuseki, keycloak, topaz, restate, litellm,
#     electric, plus userDeployments.<name>.image (as a full string)
```

**After (0.3.0)** — one blanket override:

```yaml
global:
  imageRegistry: "artifactory.corp.example.com"

# Then EITHER clear each component's registry so it inherits global:
postgresql:
  image:
    registry: ""       # clears so global.imageRegistry wins
# ...
utilImages:
  curl:
    registry: ""
  mc:
    registry: ""
  postgresClient:
    registry: ""

# OR override selectively per component if some live elsewhere:
keycloak:
  image:
    registry: "artifactory.corp.example.com"
    repository: "keycloak/keycloak"
    tag: "latest"
```

### What was refactored

**Templates now use `invincible-agent.image` helper**:
- `infrastructure.yaml`: postgresql, neo4j, weaviate, fuseki
- `keycloak.yaml`, `litellm.yaml`, `restate.yaml`, `topaz-deployment.yaml`
- `user-deployments.yaml`: pub-tools + dag-tools brokers/code-locations
- `domain-broker.yaml`: python:slim broker (previously hardcoded)
- `jobs.yaml`: restate-init curl + db-init postgresClient hooks
- `minio-bucket-init-job.yaml`: mc hook

**values.yaml split for each component**:
- Every third-party `image:` block gets `registry:` + `repository:` +
  `tag:` fields
- `global.images.*` retired; new `utilImages.*` block at bottom of
  file with same three-field shape

**User-deployments shape change** (breaking):
- `userDeployments.<name>.image: "string"` → split into
  `userDeployments.<name>.image.{registry,repository,tag}`

### Also in this bump

- **Topaz Deployment strategy: Recreate** — architect reported every
  `helm upgrade` was leaving a stuck-in-ContainerCreating topaz pod
  with a Multi-Attach error. Root cause: RollingUpdate strategy with
  a ReadWriteOnce PVC. The new pod couldn't mount the PVC while the
  old one still held it; RollingUpdate expects overlap between old
  and new pods. Fixed by switching to `strategy.type: Recreate` —
  kills the old pod first, brief availability gap during upgrade,
  no PVC conflict. Safe because topaz is single-replica with a local
  BoltDB store; no state loss.

## 0.2.4 — 2026-07-01

Patch bump. Postgres template supports Bitnami image variant.

### Behavior

- **`postgresql.imageStyle`** toggle. Two variants:
    - `postgres` (default) — Docker library `postgres` image or
      downstream mirrors. Config via `-c` args + `POSTGRES_*` env
      vars. Data at `/var/lib/postgresql/data/pgdata`. Unchanged.
    - `bitnami` — `bitnami/postgresql` image or downstream mirrors.
      Ignores command args entirely; config via `POSTGRESQL_*` env
      vars. Data at `/bitnami/postgresql`. `wal_level=logical` +
      slot/sender bumps still applied but via
      `POSTGRESQL_WAL_LEVEL` / `POSTGRESQL_MAX_REPLICATION_SLOTS` /
      `POSTGRESQL_MAX_WAL_SENDERS`.
- Overlay example (Bitnami mirror):
    ```yaml
    postgresql:
      imageStyle: "bitnami"
      image:
        repository: "artifactory.corp.example.com/bitnami/postgresql"
        tag: "16"
      auth:
        postgresPassword: "<superuser-password>"
        username: "iagent"
        password: "<iagent-app-password>"
        database: "iagent"
    ```
- Root cause: previous chart hardcoded `-c wal_level=logical` in the
  container's `args:`, which the Docker library postgres entrypoint
  passes through to the postgres binary but Bitnami's entrypoint
  script treats as a command to `exec`, failing with
  `exec: wal_level=logical: not found`.

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
