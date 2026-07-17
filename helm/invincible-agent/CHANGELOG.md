# invincible-agent helm chart — changelog

## 0.3.16 — 2026-07-17

Patch bump. Neo4j wiring becomes single-truth: set `neo4j.auth.password`
once and both the server and the fleet use it.

### Fix

- **Fleet NEO4J_PASSWORD derives from `neo4j.auth.password`** (or
  `externalNeo4j.password`) via the previously-DEAD `neo4jPassword`
  helper. Before: engines read `agentFleet.secrets.NEO4J_PASSWORD`,
  whose chart default was the literal placeholder `"xxxxx"` — a second
  truth that silently diverged from what the server booted with; the
  operator set `neo4j.auth.password` and the fleet kept sending
  `xxxxx`. An explicit `agentFleet.secrets.NEO4J_PASSWORD` still wins
  (split-topology escape hatch). NOTE: neo4j only applies `NEO4J_AUTH`
  on FIRST boot with an empty data dir — changing the password on an
  initialized PVC needs `ALTER USER` in cypher-shell or a PVC reset.
- **Duplicate `NEO4J_URI` key eliminated** — the shared ConfigMap
  carried it twice (helper-derived + a stale `agentFleet.env` default
  `"bolt://neo4j"`), and YAML last-wins pointed FRESH deploys at a
  hostname that doesn't exist; sandbox survived only because its
  overlay overrode the stale default. The stale env defaults are
  removed; the helper-derived entries now carry `hasKey` guards so an
  explicit `agentFleet.env` override never produces duplicates.
- **`NEO4J_USER` alias derived too** — most of the fleet reads
  `NEO4J_USERNAME`, `ontology_service` prefers `NEO4J_USER`; both now
  come from the same helper.

## 0.3.15 — 2026-07-17

Patch bump. `meshRegistrar.enabled` now wires the fleet, not just the
deployment.

### Fix

- **Registrar auto-wiring** — enabling mesh-registrar previously only
  DEPLOYED the gateway; engines choose the registration path per-pod
  from `MESH_REGISTRAR_URL`, which no committed file set (sandbox
  carried it only in hand-supplied release values, while its overlay
  comment claimed configmap.yaml pinned it — committed≠deployed drift).
  Seen live at work-deploy: `enabled: true`, container running, zero
  traffic — every engine silently took the legacy direct-GMS fallback.
  The shared ConfigMap now auto-sets
  `MESH_REGISTRAR_URL=http://<release>-mesh-registrar:8090` when
  `meshRegistrar.enabled`; an explicit `agentFleet.env` value always
  wins. Engines read it via ConfigMap — rollout-restart the fleet after
  flipping it on.

## 0.3.14 — 2026-07-15

Patch bump. Internal-CA/self-signed git hosts for the policy overlay.

### Add

- **`topazSeed.policySource.git.caSecretName`** — a Secret (key
  `ca.crt`) holding the CA bundle that signed the git host's TLS cert,
  mounted read-only into the clone initContainer and passed via
  `GIT_SSL_CAINFO`. Verification stays ON against YOUR CA. There is
  deliberately NO skip-TLS-verify knob: this channel delivers the
  authorization policy itself — an unverified clone would let a MITM
  serve attacker-authored grants that the sync's readback would then
  faithfully confirm (channel integrity is load-bearing for a policy
  source in a way it isn't for ordinary artifact pulls).

## 0.3.13 — 2026-07-15

Patch bump whose FIRST job is honesty about packaging: two helm changes
landed on master WITHOUT a version bump after the 0.3.12 package was
cut, and the release workflow's `skip_existing: true` silently kept the
stale package (its documented behavior — chart-releaser targeted
`a8e12f1`). The PUBLISHED 0.3.12 therefore lacks both items below even
though the repo's 0.3.12 tree has them. This release carries them; if
you pulled 0.3.12 from the chart repo, upgrade to 0.3.13.

### Add

- **Capability grant sync in the seed CronJob (ADR-0029 sixth
  namespace)** — `capability_grant_sync.py` runs as the sixth
  readback-gated sync (`capability` `invoker` relations,
  `can_invoke`); `capability_grants.yaml` is now the SIXTH REQUIRED
  overlay data file (explicit-empty `capabilities: {}` is valid;
  absence FATALs the compose — the same anti-spill posture as the
  other five, since falling back to the image copy would leak the
  sandbox's alice-grant into another cluster). Landed in the repo as
  607dabb; first PACKAGED here.
- **Seed images honor `global.imageRegistry`** — `topazSeed.image` and
  `topazSeed.policySource.git.image` accept the chart's structured form
  (`name/registry/repository/tag`, resolved via the
  `invincible-agent.image` helper), so an airgapped/Artifactory cluster
  needs only its existing `global.imageRegistry` override + a pinned
  tag (and `git.image.registry` for the docker.io-sourced alpine/git,
  which deliberately does NOT inherit the global registry — it isn't on
  ghcr). Plain-string values (the 0.3.11 form) are honored verbatim.
  The pod-level `imagePullSecrets` already covers both containers.
  `alpine/git` added to `scripts/mirror-to-artifactory.ps1`'s external
  inventory. Landed in the repo as d2f01b2; first PACKAGED here.

## 0.3.12 — 2026-07-15

Patch bump. Persona de-hardcode **phase 2**: `catalog_domain_view.rego`
drops its hardcoded persona list for a single `ds.check` on
`domain…can_view` — the walkable edge 0.3.11 seeds, prunes, and
readback-verifies. The enumeration is GONE, not parameterized: the
persona vocabulary now lives only in the directory, seeded from the
EFFECTIVE `personas.yaml`, so a deployment-overlay persona
(`overlayEnums: [personas.yaml]`) entitles identically to a shipped one
— including personas the product never shipped. With this, BOTH
vocabularies (domains 0.3.11, personas 0.3.12) are deployment-owned
data with loud-refusal validation.

### Change

- **`catalog_domain_view.rego`** — persona-enumerating loop → one
  `ds.check({object_type: "domain", …, relation: "can_view"})`.
  Fail-closed default unchanged. PRECONDITION (release-ordered): the
  0.3.11 seed must have run against the directory before this rego
  serves — the sync's `can_view` readback going green on a cluster is
  the evidence its walk has edges to find.

### Add

- **`tests/sandbox_e2e/_seal_walkable_domain_view.py`** — the
  discriminating live seal, runnable in BOTH worlds: `--expect-novel
  denied` pre-swap (proves the half-works bug: novel persona's grant +
  directory walk TRUE, authorizer FALSE) and `--expect-novel allowed`
  post-swap (entitled allows / unentitled denies / NOVEL persona
  entitles through the walk — the case the hardcoded list could never
  pass). Seeds its novel-persona overlay through the real sync and
  reverts by diff-prune.

### Migration

Upgrade normally; the seed CronJob (or a manual sync) MUST have run at
least once on chart ≥ 0.3.11 before/with this upgrade — orderly helm
upgrades satisfy this automatically since the same release carries
manifest-before-sync ordering. A cluster whose directory never received
the 0.3.11 manifest+edges would fail-closed deny catalog domain-view
until its first seed run (loud, not silent).

## 0.3.11 — 2026-07-15

Patch bump. Private-deployment policy overlays: the topaz-seed CronJob
can now source the five policy DATA files from a private git repo (or a
ConfigMap) instead of the baked-in `/app/policy`, so an org's
entitlements live in its own PR-reviewed repo (ADR-0026 git-assertion,
org-side audit trail) while the sync scripts + canonical enums keep
versioning with the product image. Merging to the tracked ref converges
the cluster on the next schedule tick — the CronJob is the reconcile
loop; no extra GitOps controllers.

### Add

- **`topazSeed.policySource`** (`type: image | configMap | git`) — where
  `users/groups/asset_grants/task_grants/ontology_compartments.yaml`
  come from. Non-image modes COMPOSE the working policy dir: all five
  data files must come from the overlay — a missing file is FATAL
  (falling back to the image's sandbox copy would silently seed sandbox
  users into a real cluster). `git` mode clones via an initContainer
  (optional PAT auth through `GIT_ASKPASS`; a failed clone fails the Job
  before any write, so an unreachable repo can never prune).
- **`topazSeed.policySource.overlayEnums`** — enum files the overlay
  ASSERTS instead of the image (default `[]` = image-canonical).
  `domains.yaml` is a deployment's classification vocabulary (labels
  must match its data tagging at ingest — the shipped set is sandbox
  demo labels, so private deployments are EXPECTED to assert it);
  `personas.yaml` is code-coupled (`catalog_domain_view.rego` hardcodes
  the persona list) — subset-safe, ADDING a persona remains a product
  change. Fail-loud both ways: asserted-but-missing FATAL,
  present-but-unasserted FATAL (two-truths guard). Mirrored in
  `validate_policy.py --overlay-enums` for overlay-repo PR CI.
- **`topazSeed.loadManifest`** (default `true`) — the seed run now
  passes `--load-manifest` with the chart-shipped
  `<release>-topaz-config` manifest on every run (idempotent). Retires
  the fresh-cluster manual extract-and-port-forward step from the
  runbook.
- **`policy/sync/validate_policy.py`** — network-free validation of all
  five data files, reusing each sync's own loaders (one definition of
  "valid"). Runs as a fail-closed gate at the top of the seed script
  (a malformed overlay refuses the WHOLE run instead of applying four
  syncs and dying on the fifth) and in a private policy repo's PR CI
  via `--policy-dir <overlay> --enums-from /app/policy`.
- **`DATAHUB_TOKEN` on the asset sync** — `datahub_topaz_sync.py` sends
  `Authorization: Bearer` when the env var is set (wired from
  `<release>-secrets`, `optional: true`). Work clusters run DataHub
  with a PAT; without this the seed job 401s. Tokenless sandbox
  DataHub is unchanged.
- **`imagePullSecrets` on the seed pod** — was missing; a private
  registry (work posture) would have ImagePullBackOff'd the CronJob.
- **Walkable vocabulary edge (persona de-hardcode, phase 1 of 2)** —
  `catalog_domain_view.rego` hardcodes the persona list because rego
  cannot LIST objects of a type: "holds ANY (persona, D) cell" required
  CONSTRUCTING candidate cell IDs, hence enumerating personas. This rev
  makes the question walkable instead: the manifest gives `domain` a
  `cell` relation + `can_view: cell->can_assume`, and `topaz_sync.py`
  seeds `domain:<D> #cell @cell:<P>:<D>` per granted cell — in prune
  scope (revoking the last grant for a cell prunes its edge) and
  readback-verified (`can_view` per entitled (user, domain), HTTP
  errors counted as loud failures, never a mid-readback crash). The
  rego is deliberately UNTOUCHED — zero behavior change; its allow
  path is proven while the old list still carries traffic. Phase 2
  (next rev) swaps the rego's persona loop for a single `ds.check` on
  `domain…can_view` and re-runs the catalog seal discriminating
  (entitled allows / unentitled denies / a novel work-overlay persona
  entitles through the walk) — after which `overlayEnums:
  [personas.yaml]` becomes fully safe including ADDING personas.

## 0.3.10 — 2026-07-02

Patch bump. Coupled-interim retirement: the `topaz.seed` values path
and `topaz-seed-job.yaml` template are removed. `policy/` + the
Python sync tool are now the single writer to topaz's Directory,
per `[[coupled-interim-mechanisms-retire-together]]`. Ships two
morning-inspection hardenings alongside: richer 403
`cell_not_entitled` context on `/orchestrate`, and a
distinguishable "no entitlements" state in the picker (both
provisioned as capture-or-lose-forever surfaces for the future
HITL access-request flow — see below).

### Remove

- **`templates/topaz-seed-job.yaml`** — deleted. Was step-1
  scaffolding whose only remaining function post-sync-tool was
  writing entitlements from `Values.topaz.seed`. Two writers to
  one authz substrate is the two-truths shape ADR-0026 kills
  everywhere else; leaving both "until the org standardizes" was
  how divergence would re-enter via our own chart.
- **`topaz.seed` values block** — removed from `values.yaml`.
  Overlays that set `topaz.seed.users` (like the previous
  sandbox overlay) should be migrated to `policy/users.yaml` in
  the repo root; both are asserted-in-git named-human decisions,
  but only `policy/users.yaml` is the durable single-truth path.

### Add

- **Richer 403 `cell_not_entitled` body** on `/orchestrate`
  (`src/iagent/gateway.py`). Per the morning-inspection review:
  every denial now records
    - `denied_at` (ISO timestamp)
    - `subject` (JWT sub) + `subject_email`
    - `session_id`
    - `requested` (persona + domains)
    - `requested_missing` (the specific domains not entitled)
    - `entitled_cells` (what the caller CAN assume)
    - `entitlement_source` (JWT-claim provenance flag)
    - `entitlements_provenance` (topaz | cache | jwt-legacy)
  Emitted at WARN level so denials aggregate to the ops dashboard.
  Same shape for 400 `incomplete_override`. This is the
  capture-or-lose-forever context the future HITL access-request
  flow will bind to; provisioning now avoids retrofit.

### Migration

To populate entitlements in a NEW cluster (existing clusters keep
their current state — the sync tool is idempotent):

```bash
# Extract manifest from the chart-shipped ConfigMap:
kubectl get cm <release>-topaz-config -n <ns> \
    -o jsonpath='{.data.manifest\.yaml}' \
    > /tmp/topaz-manifest.yaml

# Port-forward + run the sync tool WITH manifest load:
kubectl port-forward -n <ns> svc/topaz-svc 9393:9393 &
python policy/sync/topaz_sync.py \
    --topaz-url http://localhost:9393 \
    --policy-dir policy/ \
    --load-manifest /tmp/topaz-manifest.yaml
```

The `--load-manifest` flag is new in this bump — sync tool now
handles both manifest-schema-load AND entitlement-writes in one
command. Idempotent both ways.

### Discipline notes

- Coupled-interim retirement per
  `[[coupled-interim-mechanisms-retire-together]]`: seed Job's
  cause (no-way-to-write-entitlements-from-git) was fixed by the
  sync tool; keeping both writers active is precisely the
  divergence the ADR spent its whole design killing.
- Distinguishable-not-hidden empty-matrix per the morning review:
  the picker's `source==topaz && cells==0` state now renders a
  visible "no entitlements — request access" block instead of
  silently hiding, so a user whose seed silently failed sees
  SOMETHING on screen instead of "picker doesn't apply." Absent-
  vs-empty applied to the picker surface.
- 403 context is the capture-or-lose-forever seam for the coming
  HITL access-request flow. Denials without a rich structured
  body are impossible to bind a workflow to after the fact.

## 0.3.9 — 2026-07-01

Minor bump. ADR-0026 step 1 rollout: topaz Directory/Authorizer
services actually serve (were misconfigured); manifest, groups,
cells, and seed users get loaded; the `ALLOW_MOCK_AUTH` fail-open
in `dag-tools/central_gateway` is removed. This is the substrate
step for persona/entitlement authorization — no cortex-bff or
engine changes ship in this PR (those are steps 3+ of the ADR-0026
rollout, scope-held).

### Sandbox behavior change — READ THIS BEFORE UPGRADING

Before 0.3.9, DA data-access authz has been effectively fail-open
in sandbox for months, silently:

- The topaz `config.yaml` declared reader/writer/model on 8282/8383
  but omitted the `needs:` / `remote_directory` / `auth` blocks
  required to actually start those services. Topaz logged
  "disabling local directory services" and served nothing but
  the console.
- `dag-tools/central_gateway.check_topaz_authz` POSTed to
  `topaz-svc:8383/api/v2/authz/is` and got an exception (nothing
  listening at that port on the Service).
- The `except` branch fell through to
  `if os.getenv("ALLOW_MOCK_AUTH")` → `return True, None, None` —
  allow everything.
- Nobody chose "sandbox is open"; that behavior fell out of a
  misconfigured service meeting a mock flag.

After 0.3.9, topaz serves for real, the mock branch is removed
from `dag-tools/central_gateway`, and DA data-access is gated by
REAL topaz decisions. **Any DA query by a user not in
`topaz.seed.users` (in this chart's values or the overlay) will
get an honest 403.** The prior allows were a fail-open mock, not
real access; the 403 is the correct behavior. If a tester is
denied and believes they should be entitled, the fix is a one-line
addition to `topaz.seed.users` — PR-reviewed like any other
asserted entitlement per ADR-0026's "no inferred entitlements"
rule.

### Add

- **Topaz `config.yaml` rewritten with proper wiring** in
  `topaz-configmap.yaml`. Directory services (model/reader/writer/
  importer/exporter) now serve on 9292 (grpc) / 9393 (gateway);
  authorizer serves on 8282 (grpc) / 8383 (gateway — the port
  `TOPAZ_AUTHORIZER_URL` already targets, so no consumer change).
  `needs:` blocks establish startup ordering; `auth.options.default.enable_anonymous: true`
  permits intra-cluster gRPC without API keys; `remote_directory`
  points the authorizer at the local reader for identity
  resolution. Metrics moved from 9292 → 9696 to free the directory
  port; the Prometheus scrape target changes accordingly.
- **`topaz-service.yaml` exposes the new ports**: console
  (8080/8081), authorizer (8282/8383), directory (9292/9393),
  metrics (9696), health (9494). Prior version only exposed
  8282/8383/9292, which is why nothing could reach topaz's real
  APIs.
- **`topaz-deployment.yaml` container ports match** the new listen
  addresses, with descriptive port names (`console-http`,
  `authz-grpc`, `dir-grpc`, etc.) so `kubectl port-forward` is
  legible.
- **New `topaz-seed-job.yaml`** — post-install/post-upgrade Job
  that loads the ReBAC manifest into topaz's Directory and inserts
  the initial set of vocabulary objects (persona/domain enums),
  group + cell objects, and user + group-membership relations from
  `.Values.topaz.seed`. Idempotent (`topaz ds set` = upsert). Runs
  a positive control after seeding: for each user, asserts TRUE on
  every cell they're entitled to. Any red assertion fails the Job
  → fails the hook → fails the upgrade. Complies with
  `[[verification-must-fail]]`.
- **New `persona_entitlement.rego`** at `data.invincible_agent.persona.can_assume`
  — the policy cortex-bff will POST to in step 3 of the ADR-0026
  rollout. Uses `check_permission` so Topaz walks the userset
  rewrite `assumable_by: user | group#member` — group-based grants
  work through one call. Landed here (not step 3) so step 3 is
  pure client-side work.
- **`topaz.seed` values structure** — chart defaults ship
  canonical persona/domain vocabulary + a stock group taxonomy
  (aviation-stewards / aviation-engineers / defense-engineers /
  aviation-mechanics / enterprise-architects); `topaz.seed.users`
  defaults to `[]` because ADR-0026's Alternative D rejects
  chart-default-seeded entitlements as confabulation-as-authorization.
  Operators supply per-cluster.

### Remove

- **`ALLOW_MOCK_AUTH` fail-open in `dag-tools/central_gateway/main.py`**.
  Both exception and non-200 branches now `return False, None, None`
  with a loud `logger.error("TOPAZ AUTHZ DENIED: ...")` naming the
  URL, subject, URN, and cause. There is no runtime override to
  relax authz to allow-by-default. Per
  `[[coupled-interim-mechanisms-retire-together]]`: the mock's
  only remaining function post-config-fix was hiding the next
  outage.
- `ALLOW_MOCK_AUTH` documentation comment in `dag-tools/helm/dag-tools/values.yaml`
  replaced with a note explaining the removal + how to debug 403
  storms (grep logs for "TOPAZ AUTHZ DENIED").

### Verify

Post-deploy, the topaz-seed Job's built-in positive control asserts
TRUE for every seeded user's entitled cells. For the manual
TRUE→FALSE transition per `[[verification-must-fail]]`:

```bash
# Confirm TRUE for a seeded cell
kubectl exec -n <ns> deploy/<release>-topaz -- /app/topaz ds check \
  '{"object_type":"cell","object_id":"DATA_ENGINEER:AVIATION","relation":"can_assume","subject_type":"user","subject_id":"<seeded-user-id>"}' \
  -N -P -H localhost:9292

# Delete the group membership relation
kubectl exec -n <ns> deploy/<release>-topaz -- /app/topaz ds delete relation \
  '{"object_type":"group","object_id":"aviation-engineers","relation":"member","subject_type":"user","subject_id":"<seeded-user-id>"}' \
  -N -P -H localhost:9292

# Confirm FALSE for the same cell
kubectl exec -n <ns> deploy/<release>-topaz -- /app/topaz ds check \
  '{"object_type":"cell","object_id":"DATA_ENGINEER:AVIATION","relation":"can_assume","subject_type":"user","subject_id":"<seeded-user-id>"}' \
  -N -P -H localhost:9292

# Restore for continued use
kubectl exec -n <ns> deploy/<release>-topaz -- /app/topaz ds set relation \
  '{"relation":{"object_type":"group","object_id":"aviation-engineers","relation":"member","subject_type":"user","subject_id":"<seeded-user-id>"}}' \
  -N -P -H localhost:9292
```

The TRUE→FALSE transition is the `[[verification-must-fail]]` gate
that the ADR-0026 step-1 rollout requires. Delete → check-FALSE →
restore is idempotent-safe.

### Scope stop (deliberate — noted for the next PR)

Per the second-agent review of the ADR-0026 step-1 plan, this PR
STOPS at "step 1's TRUE→FALSE positive control green against real
topaz." Not shipped:

- No cortex-bff Topaz client — that's step 3, its own PR with its
  own positive controls.
- No engine `ENABLE_AGENTIC_AUTH` flip — that's ADR-0025's
  enforcement session, still fenced.
- No `policy/` YAML + CI sync tool — that's step 2, a separate
  PR where the sync tool talks to the writer API this PR wires up.

### Discipline notes

- **Why the mock got removed in the same PR as the config fix**:
  `[[coupled-interim-mechanisms-retire-together]]`. The mock's
  cause (topaz doesn't serve) is exactly what this PR fixes;
  leaving the mock would silently hide the next topaz outage.
- **Why chart-default seeds are empty**: `[[optimistic-defaults-are-dishonest]]`.
  A permissive default seed would be the confabulation-as-authorization
  pattern rejected in ADR-0026 Alternative D. Operators assert
  per-cluster.
- **Why the seed Job runs positive controls in-line**: any
  regression that broke topaz's permission evaluation would leave
  the chart deploy "green" (Job exits 0 despite no permission
  working) — the in-Job CHECK is what makes the deploy fail loudly
  when the substrate is silently broken.

## 0.3.8 — 2026-07-01

Patch bump. db-init hook now connects as the effective superuser
per imageStyle, not always as `postgres`. Fixes a CrashLoopBackOff
that surfaced only on the official-image + non-standard
auth.username path (sandbox).

### Fix

- **db-init hook branches PGUSER/PGPASSWORD on imageStyle**:
  - **Bitnami** → PGUSER=`postgres`, PGPASSWORD=`postgresPassword`
    (Bitnami's separate superuser role). Unchanged from 0.3.6.
  - **Official (`postgres` style)** → PGUSER=`auth.username`,
    PGPASSWORD=`auth.password`. On the official image, initdb runs
    with `--username=<POSTGRES_USER>` and creates that user as THE
    superuser — there is no separate `postgres` role unless
    `auth.username="postgres"` (which sandbox does NOT set;
    sandbox uses `auth.username="iagent"` per the values default).
- Bug shape: the 0.3.6 comment said "just always connect as the
  postgres superuser — the official image happens to make
  POSTGRES_USER a superuser." That's true — but only reachable as
  `postgres` if `POSTGRES_USER` was set to `postgres`. When the
  operator uses the values default (`auth.username: iagent`), the
  sole superuser IS `iagent`, and `PGUSER=postgres` fails with
  `password authentication failed for user "postgres"`. This is
  the `[[optimistic-defaults-are-dishonest]]` pattern applied to
  a template default — the previous fix was correct for the work
  cluster (Bitnami) and for any operator who happened to set
  `auth.username=postgres`, but silently wrong for the values
  default. The drift wasn't caught until sandbox got its first
  fresh chart-driven upgrade on 2026-07-01.
- No values-schema change; existing overlays continue to work.

### Discipline

- **This bug is the reason the "test the whole chart in sandbox
  first" discipline exists.** Sandbox has a different
  `auth.username` shape than work; the db-init hook design was
  correct for work but wrong for the values default. `[[integration-positive-controls]]`:
  every schema-apply migration needs a positive control that runs
  on both imageStyle paths. Not landed as part of this fix, but
  called out for the ADR-0026 rollout to build alongside the CI
  sync tool.

## 0.3.7 — 2026-07-01

Minor bump. Topaz manifest extended with ADR-0026 types (persona,
domain, group, cell) for persona/entitlement authorization. No
runtime consumer yet — this is rollout step 1 of the ADR-0026 arc
(landing the manifest ahead of the CI sync tool and cortex-bff
Topaz client so the substrate exists when the wiring lands).

### Add

- **Topaz `manifest.yaml` gains four new object types** in
  `topaz-configmap.yaml`:
  - `persona` — bare type; canonical vocabulary object (DATA_STEWARD,
    MECHANIC, DATA_ENGINEER, ARCHITECT, ANALYST from ADR-0009).
  - `domain` — bare type; canonical vocabulary object (AVIATION,
    DEFENSE, ENTERPRISE, DATA_ENGINEERING, MAINTENANCE from ADR-0009).
  - `group` — org-defined grouping with `member: user` relation.
  - `cell` — synthetic (persona × domain) object with
    `assumable_by: user | group#member` relation and
    `can_assume: assumable_by` permission.
- **Cell reification pattern** — a granted `(persona, domain)` pair
  becomes a `cell:<PERSONA>:<DOMAIN>` object. cortex-bff will
  authorize per-prompt persona/domain overrides via
  `is(user:<sub>, "can_assume", cell:<PERSONA>:<DOMAIN>)` — a native
  Topaz permission check, not a client-side graph walk.
- **ADR-0025 substrate (user + dataset types) is UNCHANGED.** Both
  ADRs share one Topaz store per ADR-0026's "single authz truth"
  decision.

### Not yet

- No CI sync tool yet — cells and grants are populated by hand for
  step-1 verification, via `topaz directory` CLI or the Directory
  gRPC API. The `policy/` YAML + sync tool land in rollout step 2.
- No cortex-bff Topaz client yet — the schema is present but no
  code path calls `can_assume`. That lands in rollout step 3.
- Retirement of the Keycloak `persona`-attribute mapper (Tier 3a
  interim) is rollout step 6; not this change.

### Verify

Apply the chart, then from a shell with `topaz` CLI:

```bash
# Confirm the new types are registered.
topaz directory get-manifest --host <TOPAZ_READER_HOST>:8282 | grep -E "persona:|domain:|group:|cell:"

# Insert a test seed by hand: user, group, cell, membership,
# grant. Confirm the permission check returns TRUE.
topaz directory set object --type user --id test@example.com
topaz directory set object --type group --id aviation-engineers
topaz directory set object --type cell --id DATA_ENGINEER:AVIATION
topaz directory set relation \
  --subject-type user --subject-id test@example.com \
  --relation member \
  --object-type group --object-id aviation-engineers
topaz directory set relation \
  --subject-type group --subject-id aviation-engineers --subject-relation member \
  --relation assumable_by \
  --object-type cell --object-id DATA_ENGINEER:AVIATION

topaz authorizer is \
  --subject-type user --subject-id test@example.com \
  --permission can_assume \
  --object-type cell --object-id DATA_ENGINEER:AVIATION
# → true

# Remove the group membership; re-run; expect false.
topaz directory delete relation \
  --subject-type user --subject-id test@example.com \
  --relation member \
  --object-type group --object-id aviation-engineers

topaz authorizer is \
  --subject-type user --subject-id test@example.com \
  --permission can_assume \
  --object-type cell --object-id DATA_ENGINEER:AVIATION
# → false
```

The TRUE-then-FALSE transition is the positive control per
`[[verification-must-fail]]` — the check must be able to return
FALSE, not just always return TRUE.

## 0.3.6 — 2026-07-01

Patch bump. db-init hook transfers table ownership to the app user
so Electric can publish.

### Fix

- **db-init hook now transfers ownership of all created tables
  (bpmn_catalog, answer_artifact_projection, projector_cursor,
  projector_skip_log) to the app user.** Electric's shape
  subscriber runs `CREATE PUBLICATION FOR TABLE ...` for each
  shape's underlying table; PG requires the caller to be the
  OWNER of the table (or a superuser). Electric connects with the
  app-user DSN, not superuser.
- 0.3.3 fixed the PG15+ public-schema privilege trap by creating
  tables as postgres superuser. That put ownership on postgres.
  0.3.6 finishes the pattern: transfer ownership back to the app
  user after schema apply. Electric can now configure publications.
- Symptom on fresh Bitnami PG17 deploy pre-fix:
    ```
    Failed to configure publication:
      42501 (insufficient_privilege)
      must be owner of table answer_artifact_projection
    ```
  cortex-bff proxy then returned 500 on every /electric/shape.

## 0.3.5 — 2026-07-01

Patch bump. cortex-bff Electric proxy default URL now uses release name.

### Fix

- **`ELECTRIC_UPSTREAM_URL` env now defaults to
  `http://{{ .Release.Name }}-electric:{{ .Values.electric.port }}`
  when unset by the operator.** Previously it fell back to the
  gateway.py source-level default of `http://iagent-electric:3000` —
  which only works if the release is named `iagent`. At work with
  release name `invincible-agent`, cortex-bff hit
  `[Errno -2] Name or service not known` on every proxied Electric
  shape request and returned 502.
- Operator overrides via `cortexBff.env.ELECTRIC_UPSTREAM_URL`
  still win over this default.
- Only emitted when `electric.enabled` is true.

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
