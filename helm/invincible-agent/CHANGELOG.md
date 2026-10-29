# invincible-agent helm chart — changelog

## Unreleased

**Policy changes (2026-10-28 ruling: pcn and pdn droppable by the alert-processors group only)**

- **`capability_grant_sync` learns `grant_to_groups`** and prunes orphan `can_drop:` objects. A
  group is written as `group:<G>#member` on `invoker`; the sync never creates the group and exits 5,
  before any write, when it is absent from live Topaz. With prune on, it deletes live `capability`
  objects named `can_drop:*` that no row names (never any other capability object).
- **Two `can_drop:` rows** in `policy/capability_grants.yaml`: `can_drop:pcn` and `can_drop:pdn`,
  both `grant_to_groups: [alert-processors]`. A kind is gated iff `capability:can_drop:<kind>`
  exists, so deleting a row reopens the kind to every caller.
- **Nothing gates a drop until Lane 1's door lands.** These rows are inert data until it does.
- **The sync must also run in the task-grant-sync hook Job** (Lane 1's change); this entry does not
  wire it.
- **Before that roll, a human `topaz_sync` must create `group:alert-processors`** (new group in
  `policy/groups.yaml`, alice in `policy/users.yaml`), or the capability leg exits 5.

- **The `can_export:<profile>` convention** (header comment in `policy/capability_grants.yaml`):
  who may export export profile `<profile>`, deny-by-default (no row, nobody). `validate_policy`
  gains three refusals: a `can_export:` key naming an unknown profile; a profile name in both the
  review-export and fin CDRL sets; a review-export profile with no row (default row
  `grant_to_groups: [alert-processors]`). A CDRL row is allowed, not required, pending a ruling.
  **No rows ship**, so nothing to sync and no roll precondition.

**Chart changes**

- **A `recipient_readers` policy rail.** Who may download a recipient's disclosure package, from
  the engine that owns the scope, becomes a git-asserted Topaz relation (architect, 2026-10-27
  ruling 4, refined 2026-10-28). The Topaz manifest gains a `recipient_scope` type
  (`reader: user`, `can_read_recipient`; object id `<owner>:<scope>`, owner `finance` | `cost`),
  and the `task-grant-sync` Job gains a last leg, `recipient_reader_sync`. In the configMap/git
  overlay modes `recipient_readers.yaml` is optional: absent logs a `WARN:` and skips the leg
  (no reader asserted, every recipient check denies); whether absence becomes FATAL is open.
  `policy/recipient_readers.yaml` ships with both owners empty; the finance and cost lanes move
  their own rows. No engine reads the rail yet. Loading the new manifest type is done by the
  existing `topaz-manifest-load` Job.

## 0.4.71 — 2026-10-28

Cut from master `4a5ff6b6` (architect, 2026-10-28), so that the work cluster installs a version
and never a master sha. Sandbox has run these images since roll 221, by `global.imageTag`. It
carries every master merge since 0.4.70 (`b59e4a0f`): #112, #95, #108, #101, #107, #113, #118,
#120 and #121.

**Chart changes**

- **The default values pin the frontend.** `cortexUi.image.digest` in `values.yaml` →
  `sha256:57e40789…`, cortex-ui `e09e2ac`, which re-pins its producer to `4a5ff6b6`'s published
  contract. Until 0.4.70 the default was empty and fell through to `:latest`. An environment's
  own values still override it. `values-sandbox.yaml` moves to the same digest, from `c02ee0d2…`
  (cortex-ui `e0c3c6d`).

**Images.** A chart bump restarts every pod.
- **cortex-bff (`src/iagent`):**
  - `GET /ingest/{id}/extraction` serves doc-tools' `wire_evidence_ref` unchanged, and the
    published `EvidenceRef` is exactly `{page, bbox, note?}` with `additionalProperties: false`
    (#121, PCN-2683). A row with no ref, or with a ref that fails the contract, is served
    `evidence_ref: null` and counted. A failing ref also logs one WARNING naming the check. The
    old synthesized keys (`page_dims`, `bboxes`, `units`, `quality`) are gone; a review.json
    written before doc-tools v0.2.2 now reads `null` on every row.
  - a 409 that asks is declared as a refusal, with its grantor (#107).
- **finance-agent:** program enumeration and resolve return only the programs the caller
  `can_view_program` (#113).
- **Policy baked into the images:**
  - edge-02 task audiences mirror edge-01's, and the OpenDDIL maintenance-fault event kind's
    domain is MAINTENANCE (#118);
  - the openddil-lab course row mirrors doc-tools' third pass, `render.pages` (#120).

**⚠ Before installing on a cluster that has not synced Topaz since #118:** `task_grants.yaml`
names three new groups (`maint-approvers-edge-02`, `maint-tier-ack-edge-02`,
`maint-supervisors-edge-02`). Sync Topaz first, or `task-grant-sync` exits 5 and the release
reads failed. Sandbox was synced before roll 220.

**No deploy effect:** #95 (tests), #101, #108 and #112 (docs and sessions).

## 0.4.70 — 2026-10-26

Roll 208. It carries every master merge since 0.4.69 (`7a45a3cb`): #93, #100, #97, #99, #96,
#106, #105, #104, #109, #102, #103 and #110.

**Chart changes**

- **A public client puts itself in its access token's `aud` (#110).** The architect ruled on
  2026-10-26 that the `training-workbench` client emits `authz_id` and `aud`. wb's api accepts a
  token only when `aud` names `training-workbench`.
  - Every `keycloak.publicClients` entry gets an `audience-self` mapper: `oidc-audience-mapper`,
    with `included.client.audience` set to the client's own id, on the access token only.
  - It ships in the realm import, in the reconcile's create, and in the reconcile's repair of a
    live client. The repair keys on what a mapper emits, not on its name, and never rewrites an
    existing mapper.
  - The readback judges the audience and its access-token flag on one mapper's config, in any
    key order. The ok line becomes
    `ok   training-workbench public, pkce S256, emits authz_id, aud training-workbench`.
- **cortex-ui's redirect readback compares sets (#100).** 0.4.69's readback compared the
  redirect lists in order. Keycloak serves them in its own order, so revision 217 failed a
  correct realm. The readback now compares them as sets.

**Release pipeline (#93).** The chart release now needs the image build, and a missing image is
fatal. 0.4.66, 0.4.68 and 0.4.69 each published a manifest with 0 of 19 images tagged, because
the retag ran before the build finished.

**Images.** A chart bump restarts every pod, so all of these land on this roll.
- **cortex-bff (`src/iagent`):**
  - a seeded canvas answer names its template, and a finance canvas asks which program (#97);
  - ingest-v1, a published contract with a shape lock, and the status row that names the task a
    steward acts on; a zero-row notice is asked about, not failed (#99);
  - a has-parts defect filing with no requester is a terminal 422 (#104);
  - `/canvas/seed` declares its 200 and 409 bodies (#103);
  - a policy refusal names its policy, the missing binding, and who can grant it (#96).
  - **One schema change:** `ingest_status_projection` gains `force_text_fallback BOOLEAN NOT NULL
    DEFAULT FALSE` (#99). cortex-bff adds it on startup with `ADD COLUMN IF NOT EXISTS` and logs
    `ingest_status_projection migration applied`; a failure logs a warning and leaves the
    ingestion seam dormant.
- **presentation-agent:** `safety:FailureRecordSet` binds `KNOWLEDGE_DOCUMENT`, matching cortex
  (#105).

**No deploy effect:** the lane-trailer hook (#106), and the test-only #109 and #102.

## 0.4.69 — 2026-10-25

**Finding: the `cortex-ui` client accepted any redirect.** Its realm import carried
`redirectUris: ["*"]` and `webOrigins: ["*"]`. cortex-ui is a public client. Anyone who got a
signed-in user to click a crafted login link could name their own redirect and collect the user's
authorization code, and with it a token. The architect raised it on 2026-10-24 (PR #91). It is the
shape `keycloak.publicClients` already refuses.

**The fix: the redirect set is cortex-ui's literal origin.**
- cortex-ui sends one redirect, `window.location.origin`. Its `/case/<id>` and `/ask` deep links
  ride in OIDC state, never in the redirect. So the set is `https://<host>` and
  `https://<host>/`, with no paths.
- The web origin is `https://<host>`, and the post-logout redirect is `https://<host>/`, held
  separately.
- **New `keycloak.cortexUiClient` keys:** `redirectUris`, `webOrigins` and
  `postLogoutRedirectUris`. When they are empty, the set derives from the TLS hosts of
  `cortexUi.ingress`.
- **When there is no set**, neither declared nor derivable:
  - the import emits no redirect, so it fails closed;
  - the reconcile job leaves the live client alone, and prints
    `WARN cortex-ui: live redirectUris holds a wildcard` when it has one.
- The render fails on any `*`, on a non-https URI, and on a web origin with a path.

**The realm reconcile job converges a live realm.** This is the job's one declared exception to
additive-only.
- It reads the full client and replaces exactly those three fields. It PUTs the client back only
  when they differ.
- The readback fails unless all three are the rendered literals and the client is still public.
- The success line is `ok   cortex-ui redirects <n> literal, no wildcard`.

**Every deployment's realm has the same hole.**
- A deployment whose `cortexUi.ingress` lists its TLS hosts is fixed by this roll.
- **Work's realm needs the same fix.** If work serves cortex-ui through its own ingress, or through
  none of the chart's, it must declare `keycloak.cortexUiClient`. Until then the job only warns,
  and the wildcard stays.

**Related, unchanged: cortex-ui keeps `directAccessGrantsEnabled: true`.** The sandbox walks and
the e2e harness sign in with the password grant. A public client with the password grant takes a
user's password directly. It is recorded here and is not changed by this release.


## 0.4.68 — 2026-10-24

A declared list of public PKCE clients, `keycloak.publicClients` (PR #90, on the architect's 10-24
ruling). Its first member is `training-workbench`, the training workbench's login.
- Each client is public, standard flow with PKCE S256 required, no implicit flow, no password
  grant, no service account, `fullScopeAllowed`. When the identity claim is not `email`, it gets
  the `authz-id-user` mapper.
- The render fails on an empty or duplicate clientId, a clientId that collides with a client the
  chart already defines, an empty redirect set, a redirect that is not https with a literal host,
  and a `*` web origin.
- The realm reconcile job creates a missing client and repairs a missing mapper. It never rewrites
  an existing client. Its readback fails unless the live client is public, PKCE S256, has no
  password grant, carries every declared redirect, and emits the claim.
- The default is `[]`, which renders nothing new. `values-sandbox.yaml` declares
  `training-workbench`.
- The version also moves past 0.4.67, whose roll (rev 216) failed in its post-upgrade hooks.

## 0.4.67 — 2026-10-24

The supervisor's `/classify_predicate` budget goes from a literal 30 s to `CLASSIFY_PREDICATE_TIMEOUT_S = 60`.
This is an interim, on the architect's 10-24 ruling, on the same terms as the resolve budget.
- No template, `values.yaml` default or `values-sandbox.yaml` key changed.
- The only code change is `src/iagent/defs/dynamic_supervisor.py`, which is Dagster user code. Every
  image is still re-tagged at the merge sha.
- cortex-ui stays `e0c3c6d`.

## 0.4.66 — 2026-10-24

Roll 207. No template or `values.yaml` default changed. The release carries 207's engines and one
sandbox-only change: `values-sandbox.yaml` `cortexUi.image.digest` → `sha256:c02ee0d2…`
(cortex-ui e0c3c6d, PR #29, kind at drop). It must roll with 207's BFF, whose `POST /ingest`
takes the `leaf` cortex now sends.

## 0.4.65 — 2026-10-22

The domain broker can install from a mirror, for a deployment with no route to github.com or
pypi.org. Before this, its start-time pip install always fetched the SDK tarball from GitHub and
everything else from PyPI, and in a closed network it retried until the startup probe gave up.
New `domainBroker` keys:

- `meshSdkSource`: `url` (the default; the GitHub tag tarball, as before) or `index`, which
  installs `iagent-mesh==<meshSdkVersion without the v>` from the pip index.
- `meshSdkBaseUrl`: replaces the GitHub tags URL. The file name stays `<meshSdkVersion>.tar.gz`.
- `pip.indexUrl` becomes `PIP_INDEX_URL`.
- `pip.caSecretName` names a Secret holding `ca.crt`; it is mounted and passed as `PIP_CERT`.

There is no skip-verify option. Defaults render as before. Sealed by
`tests/test_domain_broker_installs_from_a_mirror.py`.

## 0.4.64 — 2026-10-22

The topaz-seed CronJob, in `configMap` and `git` mode, copies all eight data files that
`validate_policy.py` requires. It copied six: `domain_consumption.yaml` and `program_members.yaml`
were missing from the copy loop. So from 10-02 every run in those modes was refused `MISSING`.
Sealed by `tests/test_topaz_seed_compose_copies_every_validated_file.py`.

## 0.4.62, 0.4.63 — 2026-10-22

No template or `values.yaml` default changed. Both carry sandbox-only changes in
`values-sandbox.yaml`, and 0.4.62 also adds a `values.yaml` comment on the promotion row-edit flags.

## 0.4.61 — 2026-10-20

Sandbox only, for roll 198. `cortexUi.image.digest` pins cortex-ui `3d2f7a3` (`sha256:7b51701c`,
refusal reasons in the toast), and `cortexBff.env.IAGENT_PROMOTION_ROW_EDITS` is `"true"`. cortex's
`VITE_REVIEW_ROW_EDITS` stays `"false"`, so the server takes row_edits on a promotion and no UI sends
them yet.

## 0.4.60 — 2026-10-19

`primeSubstrate.reregisterEngines.deployments` gains `cortex-bff`. The BFF now persists each
frontend's render menu in Postgres (`frontend_menu`) and replays it into the graph at startup
(architect ruling Q9), so the post-prime restart is what puts cortex's menu back after a wipe.
The list entry is the only chart change; the BFF's login-time post becomes a no-op when the
stored menu matches and the graph still holds it.

## 0.4.59 — 2026-10-19

`cortexBff.env.IAGENT_PROMOTION_ROW_EDITS: "false"` in `values-sandbox.yaml`. The BFF can now take
steward corrections (`row_edits`) on a `document_promotion`, behind this flag. It ships off and goes
on together with `cortexUi.env.VITE_REVIEW_ROW_EDITS` once one live correction is proven. Values
only; no template changed.

## 0.4.58 — 2026-10-19

cortex-ui pinned to 3bd3e80 (`sha256:2b61d76f…`), from 1f5482f (`1f3ae4ed`). The pdf.js worker
`.mjs` is served as JavaScript, so the source pane draws; the pane names the real failure.
Frontend image only; no template changed.

## 0.4.57 — 2026-10-18

cortex-ui pinned to 1f5482f (`sha256:1f3ae4ed…`), from b3bdab7 (`94599a96…`). Promote is
held when there are no rows or no drawn source page; Reject offers the four ruled codes; a
`?idp=openddil` deep link starts the brokered login. Build stage, entrypoint and nginx
config unchanged. Frontend image only; no template changed.

## 0.4.56 — 2026-10-18

cortex-ui pinned to b3bdab7 (`sha256:94599a96…`), from 9b23135 (`5c411756…`). Carries the
`/case/{id}` and `/ask?q=` deep links. Only the build stage moved (node 22); the runtime
entrypoint and nginx config are unchanged. Frontend image only; no template changed.

## 0.4.55 — 2026-10-17

cortex-ui pinned to 9b23135 (`sha256:5c411756…`), from 68f56bb (`5d5b5dbb…`). Adds the
MODEL_EXPLANATION card behind the `modelCanvas` feature flag. The image's entrypoint reads
`VITE_FEATURES` at runtime (default empty) and the chart sets none, so the card stays off. Frontend image only; no template changed.

## 0.4.54 — 2026-10-17

cortex-ui pinned to 68f56bb (`sha256:5d5b5dbb…`), from 8fe23fc (`cc2ad9cc…`). Carries the review
card to the 10-17 standard, xml drops accepted, and /ingest/mine paging past 50. Frontend image
only; no template changed.

## 0.4.53 — 2026-10-17

cortex-ui pinned to 8fe23fc (`sha256:cc2ad9cc…`), from e1b94e2 (`8d0234ab`). The rail reads
GET /ingest/mine on load, and a retried drop sits at its latest activity. Frontend image only;
no template changed.

## 0.4.52 — 2026-10-16

Renumbered again, to 0.4.52: roll 190 took 0.4.51. Before that it was 0.4.51 (rev 189 rolled as
0.4.49 and #41 merged as 0.4.50), and before that 0.4.49, renumbered from 0.4.41 when master was
at 0.4.46, lane/01-broker-flip (#41) held 0.4.47 and lane/01-rev189 held 0.4.48. On 2026-10-10 it
was renumbered from 0.4.40, when rev 186 took 0.4.39 and lane/01-oidc-roundtrip moved to 0.4.40.
Content is unchanged by any renumber.

NetworkPolicy gate: the cuts a dry-run evaluator found in cortex-bff and engine-o. The gate stays
OFF in the sandbox; nothing rolled.

### Added

- **`invincible-agent.networkPolicyEgressOnlyTargets`** (`_helpers.tpl`): components an engine may name
  in `directCallers` that are neither stores nor engines (`dagster-webserver`, 3000). Renders the
  engine's egress rule and no ingress policy. Needed for `DAGSTER_WEBSERVER_URL`, a flow no other
  table could express.

### Changed

- Sandbox `networkPolicy.directCallers`: engine-o gains postgresql, keycloak, central-gateway,
  dagster-webserver; cortex-bff gains weaviate, fuseki, topaz. Each carries its `via` key and the
  2026-12-14 expiry. See docs/measurements/2026-10-10-the-gate-keeps-cortex-bff-and-engine-o.md.

## 0.4.51 — 2026-10-16

A finished case's Restate workflow is kept 30 days, not Restate's default 1.

### Added

- **`restate.caseWorkflowRetentionDays`** (default `30`). `templates/engines.yaml` renders it into the
  engine-a Deployment as `CASE_WORKFLOW_RETENTION_DAYS`; the runner puts it on its `run` handler as
  `workflowCompletionRetention` in discovery. The runner refuses to import below 1 day. Retention is
  fixed when the handler registers: restate-init re-registers engine-a with `force`, so a roll applies it.

## 0.4.50 — 2026-10-16

(Written as 0.4.44 on 2026-10-12; renumbered to 0.4.46 when master reached 0.4.45, to 0.4.47 when
rev 188b took 0.4.46, and to 0.4.50 when rev 189 merged first as 0.4.49.)

The OpenDDIL broker flip, now ON in `values-sandbox.yaml`. The client secret is the only secret, by
reference: Secret `openddil-broker-client`, key `client-secret`. Keycloak trusts OpenDDIL's issuer
through their lab CA ("OpenDDIL Lab Internal CA", CA:TRUE, pathlen:0), whose PEM is in Secret
`keycloak-openddil-trust` key `ca.pem`. Both Secrets are created out of band. Sits on PR #29
(lane/01-oidc-roundtrip).

Correction: the 0.4.47 text of this entry said "pinning exactly its self-signed leaf. There is no lab
CA." That was wrong. OpenDDIL's issuer chains to a lab CA, and the CA is what is trusted.

### Added

- **`keycloak.brokers.<name>.clientSecret`** (default `""`; set ONLY in a gitignored `*.secret.yaml`).
  `templates/secrets.yaml` renders it into `<release>-secrets` key `broker-<name>-client-secret`, and
  the reconcile job reads it by `secretKeyRef`. `brokerActive` is now enabled AND (existingSecret OR
  clientSecret). Never in a ConfigMap, the job script or an env literal.
- **`keycloak.truststore`** (`enabled`, `existingSecret`, `existingConfigMap`, `key`, `mountPath`): extra
  PEM trust for Keycloak's JVM (`KC_TRUSTSTORE_PATHS`) from a Secret (or, alternatively, a ConfigMap)
  created out of band, mounted read-only. Exactly one source must be set; zero or both fails the render.
  The chart cannot see the content of an existing Secret: the `checksum/truststore` annotation hashes
  source kind + name + key, so a rotation means replacing the Secret AND restarting Keycloak.
  The `caPem` value was removed (setting it fails the render): the cert is not a secret and does not go
  in the secret values file.
- **Guard:** an enabled broker with an `https:` issuer fails the render unless `keycloak.truststore` is
  enabled or `brokers.<name>.publicCA: true`, so a self-signed issuer cannot flip on silently untrusted.
- `values-sandbox.yaml`: OpenDDIL's real issuer and `iagent-broker`; both switches `true`;
  `brokers.openddil.existingSecret: openddil-broker-client`;
  `truststore.existingSecret: keycloak-openddil-trust`, `key: ca.pem`. The lab CA's PEM is in that
  Secret, created out of band (`kubectl create secret generic keycloak-openddil-trust
  --from-file=ca.pem=<lab-ca.pem>`). No secret value is in any values file.

### Tests

- `tests/test_oidc_broker_flip_dry_run.py`: six arms (flip is the switches, secret by reference only,
  CA reaches Keycloak, untrusted issuer refused, reconcile against the fake Keycloak, committed values
  enable the broker by reference only).
- `tests/test_oidc_broker_chart.py`: truststore arms for existingSecret, neither/both sources, caPem
  removal, disabled, and the committed sandbox values.
- Existing broker tests now set `publicCA` where they enable the broker.

### Also in this release: written as 0.4.40 on 2026-10-10, a number master then released as rev 186b (tag invincible-agent-0.4.40) without this content

Renumbered from 0.4.39: rev 186 takes 0.4.39 (architect directive 2026-10-10).

Retired users leave the live realm; the OpenDDIL broker segment is tested by round trip.

#### Added

- **`keycloak.retiredUsers`** (base `[]`; sandbox: `operator.atlantia`, `operator.borduria`,
  `liaison`). Chart 0.4.36 removed these mirrored email users from `nonInteractiveUsers`, but the
  reconcile job is additive, so they survive in any Keycloak first booted earlier. Per name: exact
  username lookup; DELETE only when `federated-identity` is `[]` (a linked user is a brokered
  shadow, kept and logged); the readback FAILS if the name still exists without a link. The render
  fails for a name also in `nonInteractiveUsers`/`localHumanUsers` or not a plain username.

#### Tests

- `tests/test_oidc_broker_realm_roundtrip.py`: round trip against a stateful Keycloak admin-API
  double seeded from a realm export, assertions on the exported JSON, retired-user behaviour, and
  join seals binding policy grants to the brokered sub.

## 0.4.49 — 2026-10-16

Rev 189, the label it rolls under. The door-read flag below is chart content added after 0.4.48's
bump, so the version moves (`tests/test_chart_version_tracks_chart_content.py`). 0.4.48 was never
published or deployed. 189 merges before #41 (`lane/01-broker-flip`, 0.4.47), so #41 renumbers
above this (0.4.50), and #28 after it.

### Added

- **`cortexBff.env` `INGEST_DOOR_READS_PROCESSABLE_KINDS: "false"`.** `POST /ingest` can refuse a
  registered kind that doc-tools does not process, using the list doc-tools publishes to the new
  service-only `PUT /ingest/processable-kinds` (persisted in Postgres, cached per pod). The flag
  ships OFF, so registry behaviour is unchanged; it is flipped ON in 190 after doc-tools
  publishes. ON is deny-by-default: 503 `processable_kinds_unknown` before the first publish,
  400 `kind_unprocessable` after.

## 0.4.48 — 2026-10-16

Rev 189's first label, never published: the iagent-mesh `v0.9.10` pin. Rolled as 0.4.49, above.

### Changed

- **`domainBroker.meshSdkVersion` `v0.9.8` → `v0.9.10`.** The broker takes the same inbound
  transport-auth dependency as the fleet, and `tests/test_lock_coherence.py` asserts the two are
  equal. The fleet's 0.9.10 pin left it at 0.9.8.

## 0.4.46 — 2026-10-15

Rev 188b. The fleet image carries #46 (saf), #47 (gov's caller census at bb0b5190, with #52's
test persona), #51 (one identifier namespace, one claimant) and the walk's capability check asked
as the run's acting identity rather than the case runner. The fleet imageTag is set at roll time,
not here. #41 (lane/01-broker-flip) renumbers to 0.4.47 when it merges.

### Changed

- **`values-sandbox.yaml` `cortexUi.image.digest` → `sha256:8d0234ab…` (cortex-ui e1b94e2).**
  cad and xml are drawn "not yet accepted" and only pdf sends, a door 4xx draws as a refusal,
  every walk row names its persona, and `npm audit` is at zero. The tag-to-digest binding was
  measured before pinning; the values comment records how.
- **`values-sandbox.yaml` `cortexUi.env.VITE_REVIEW_ROW_EDITS: "false"`.** Steward row edits are
  off on the sandbox. The architect's condition for keeping them on was one confirmed live
  correction, and none exists: no grouped review has been acted on since 2026-10-10. Removing the
  key turns them back on.

## 0.4.45 — 2026-10-13

Rev 188. The 188 image carries the structured `failure` field, `GET /ingest/retries` (the
service-only listing doc-tools polls to relaunch retried drops) and the door 400 on `POST /ingest`
(a drop with no registered content kind is refused before anything is written). The fleet
imageTag is set at roll time, not here. #41 (lane/01-broker-flip) renumbers to 0.4.46 when it
merges.

### Added

- **`cortexBff.env` `INGEST_RECEIVED_TIMEOUT_SECONDS: "600"` and
  `INGEST_WATCHDOG_INTERVAL_SECONDS: "30"`.** The ingest watchdog's two knobs, now tunable from the
  chart. 600 s is the architect's 2026-10-12 bound, deliberately longer than doc-tools' 30 s
  sensor tick, because a run queued behind max_concurrent_runs sits at `received` legitimately; a
  timeout failure is provisional until a run starts. A value <= 0 disables the watchdog.

### Changed

- **`values-sandbox.yaml` `cortexUi.image.digest` → `sha256:7b2b6129…` (cortex-ui 88a65d4).**
  The upload now sends `content_kind`, a failed drop draws its `failure` and offers Retry,
  `row_edits` is on by default, and the walk fixes (#19–#22) are in. The tag-to-digest binding was
  measured before pinning; the values comment records how.

## 0.4.44 — 2026-10-12

Rev 187c, a frontend-only pin, rolled ahead of 188 on the architect's direction. The fleet image
is unchanged (49aa5e28). #41 (lane/01-broker-flip) also claims 0.4.44 on its branch and
renumbers when it merges.

### Changed

- **`values-sandbox.yaml` `cortexUi.image.digest` → `sha256:facdc367…` (cortex-ui f3617a9).**
  A drop is now an ingest entry on the answers rail, and "My drops" is gone. The build also
  carries the walk login fix and `WALK_SPKI_PIN` (#17). The tag-to-digest binding was measured
  before pinning; the values comment records how.

## 0.4.43 — 2026-10-12

Rev 187b, a frontend-only pin. #41 (lane/01-oidc-broker) also claims 0.4.43 on its branch and
renumbers when it merges.

### Changed

- **`values-sandbox.yaml` `cortexUi.image.digest` → `sha256:2556cf5b…` (cortex-ui b566192).**
  This build includes cortex #10 (3fa6fcb, the answers perf merge), and pinning it was
  conditional on that. It also carries #4, the composer: rev 187 rolled on 865c080, which lacks
  it. The tag-to-digest binding was measured before pinning; the values comment records how.

## 0.4.42 — 2026-10-11

Rev 187, second chart change: answers at scale (#42, lane/01-answers-at-scale, numbered 0.4.44 on
its branch) and the group-audience exit code (#35, lane/01-group-audiences). Renumbered at merge;
0.4.41 below is the rev's first.

### Added

- **`answer_artifact_projection` gains `archived_at`, `archived_by`, `archive_reason`** and two
  indexes (`files/sql/create_answer_artifact_projection.sql`): `idx_aap_user_created`
  (newest-first paging per user) and `idx_aap_search_tsv`, an EXPRESSION GIN index over
  question_text + summary. Not a generated column, because Electric refuses to replicate one.
  Every statement is idempotent (`IF NOT EXISTS`), so the existing schema job applies it to a
  live table.

### Changed

- **`task-grant-sync-job.yaml` documents exit code 5:** a `grant_to_groups` entry names a group
  object absent from live Topaz (REFUSED, nothing applied). `set -e` already fails the Job on it;
  the change is to the header comment only.

## 0.4.41 — 2026-10-11

Rev 187. Two walkers, and the reconcile creates a local human the live realm lacks (6c93b1c2).
Numbered here because the release guard refused 0.4.40 for 6c93b1c2's helm change. Open
branches that also claimed 0.4.41-0.4.44 (netpol, prep-next, #41, #42) renumber at merge.

### Added

- **`erin` and `chris`** in `keycloak-configmap.yaml` and `values.yaml` `localHumanUsers`.
- **`realm-reconcile-job.yaml` creates any `localHumanUsers` entry the live realm lacks.** The realm
  import applies only to a fresh realm, so a user added later otherwise never exists. The loop is
  create-if-absent and never touches an existing user.

## 0.4.39 — 2026-10-10

Rev 186. The Dagster instance config is in the chart, and it bounds how long a run may stay
STARTED (lane/74-dagster-max-runtime, PR #23; numbered 0.4.37 on its branch, renumbered here).

### Fixed

- **A STARTED run whose code-location pod died is failed after `maxRuntimeSeconds`**
  (`templates/dagster-instance.yaml`, `values.yaml` `dagster.runMonitoring`). Under
  `DefaultRunLauncher` the run monitor cannot check a worker's health. It still applies the
  runtime bound, but the instance config set none, so a zombie held one of the two
  `max_concurrent_runs` slots for ever, and two of them hung every question. The bound is 3600s,
  about 1.9x the longest finished run measured on the sandbox (1930s, from 2742 runs, 2026-10-09).
- **The instance config is chart-owned.** Before this it was a ConfigMap made by hand and
  patched by hand into the webserver, daemon and user-code Deployments, so no install from the
  chart could reproduce it. The new ConfigMap is `<release>-dagster-home`, a name helm can own.
  The volume keeps the live name `dagster-instance` and the same mountPath, so the upgrade
  re-points the hand-patched volume rather than adding a second one. A `checksum/dagster-instance`
  annotation rolls the three pods when the config changes. The hand-made ConfigMap is left
  orphaned, and deleting it is a human's call after the roll.
- The "production would use K8sRunLauncher" comment is corrected. A dead worker under
  `DefaultRunLauncher` IS caught, by the runtime bound.

## 0.4.38 — 2026-10-10

Rev 185 (rev 184 was the rollback to 182). Realm-reconcile repairs its own stale mappers.

### Fixed

- **`realm-reconcile` no longer fails the release on chart-written `authz-id-svc` mappers.** Rev 183
  (0.4.36 flipped sandbox `keycloak.authzClaim` `email` -> `authz_id`) failed at realm-reconcile:
  all 17 service clients still carried the mapper the chart itself wrote at 0.4.35 (`claim.name`
  `email`), the Job only ever created a MISSING mapper, and the readback then refused every one.
  Ownership rule: a mapper whose `claim.value` is the chart's declared `authzId` is the chart's, and
  its stale `claim.name` is now migrated in place (PUT on the same mapper id, value unchanged); a
  mapper with any other value is the operator's, is never touched, and still fails the readback
  (now worded "operator-owned mapper, not migrated"). The `cortex-ui` `authz-id-user` mapper is not
  migrated (it passed readback live).

## 0.4.37 — 2026-10-10

Rev 183.

### Added

- **`engineSafety.failureSourceConnectors`** (default `""`) renders `FAILURE_SOURCE_CONNECTORS` into
  the shared `-config` ConfigMap only when non-empty; an explicit `agentFleet.env` entry wins. The
  sandbox leaves it empty (the FRACAS fixture): no connector module ships in any image yet.

### Changed

- Sandbox `cortexUi.image.digest` -> `1985ce7f` (cortex-ui 9bf8063: the `refusal` reader, the
  stale-tab guard, the FRACAS bindings). Replaces the 182a hand-set image (`e06fbeb2`, 415e5e6).

## 0.4.36 — 2026-10-08

OIDC brokering to the OpenDDIL realm, and one identity claim for every species. Not rolled.

### Added

- **`keycloak.brokers.openddil`** (default disabled; the sandbox keeps it off, with a placeholder
  issuer, until OpenDDIL supplies issuer + client + secret). The realm-reconcile job upserts the `oidc` IdP (discovery, syncMode FORCE, trustEmail
  false, storeToken false, PKCE), a sub -> `authz_id` mapper, a username mapper, and the
  `openddil-first-login` flow: a copy of "first broker login" with review-profile and every
  link-existing-account execution DISABLED. Every step is read back. The client secret reaches the
  job only through `existingSecret`/`secretKey` (secretKeyRef); the broker renders only when enabled AND existingSecret is set.
- **`USER_ENTITLEMENT_CLAIM`** is rendered in the shared `-config` ConfigMap from
  `keycloak.authzClaim` (base default `email`; the base render differs from 0.4.35 by this one
  line). `keycloak.localHumanUsers` lists the local humans that get the claim as a user attribute.

### Changed

- The sandbox sets `authzClaim: authz_id`. Local humans carry the attribute (realm import and
  reconcile); the `cortex-ui` client gets an attribute mapper; the reconcile job sets the realm
  user-profile `unmanagedAttributePolicy` to ADMIN_EDIT. A service client created before the flip
  keeps its old `authz-id-svc` claim name: the reconcile readback FAILS it (exit 4); the repair is
  to delete the stale mapper and re-run.
- `operator.atlantia`, `operator.borduria` and `liaison` leave the sandbox `nonInteractiveUsers`;
  `iagent-openddil` acts on behalf of the brokered principals. The onBehalfOf check accepts a
  principal of an enabled broker, and `DELEGATE_ON_BEHALF_OF` carries the principal's `sub`.

## 0.4.30 — 2026-10-04

engine-o is restarted by the re-register hook like every other engine that registers on boot.

### Fixed

- **`primeSubstrate.reregisterEngines.deployments` gains `engine-o`** (`values.yaml`). Its
  lifespan registers the SUSTAINMENT `mesh:resolveInstance` provider, so it has the property the
  list exists for. It was excluded as the registry consumer, and the comment saying so is
  corrected. At roll #16 the hook restarted every listed engine at 00:59, after the stores came
  up. engine-o was not listed, booted without Weaviate, and stayed cold until a hand roll at
  02:26.
- **The coverage seal has no waiver list** (`tests/test_reregister_covers_every_registering_engine.py`).
  `WAIVED_BY_DESIGN` held only engine-o, and is deleted. Excluding a registering engine now
  means changing the seal, not appending a line to it.
- The other half is in engine-o's own lifespan (store-gate): Weaviate is retried until it
  answers, so a pod booted during an outage recovers without any restart.

## 0.4.29 — 2026-10-03

The reserved set is every StatefulSet that claims a volume, not a list of three.

### Fixed

- **PostgreSQL, Neo4j and Fuseki join the stateful core** (`templates/infrastructure.yaml`).
  They now carry `statefulSpreadLabel` and `statefulSpreadAffinity` in place of
  `avoidStatefulNodes`, as Keycloak, Restate and Weaviate already did. Before this, all three
  claimed a `local-path` volume and still carried the REQUIRED avoid rule. Roll #16 left Neo4j
  Pending once the node holding its volume was labelled. The first roll with the spread chart
  found one stateful workload missing from its own reserved set.
- **The seal derives the set** (`tests/test_stateful_core_resources_and_spread.py`). The
  stateful-core pod templates must equal the rendered StatefulSets that have
  `volumeClaimTemplates`, which replaces a hard-coded count of 3. Mutant: Neo4j reverted to
  `avoidStatefulNodes` makes `test_stateful_core_pod_templates_do_not_avoid_stateful_nodes` red
  ("claim a volume").
- The comments in `_helpers.tpl` and `values.yaml` no longer name three members.

## 0.4.28 — 2026-10-03

Patch bump for the ingest/origin seam (SDK lane/ca-0.9.7), which adds two env keys to the
agent-fleet ConfigMap.

### Changed

- **`templates/configmap.yaml` gains `CONTENT_KIND_OVERLAY_DIRS`** (default
  `/app/policy/overlays/openddil-lab/content_kinds`), parallel to `TASK_KIND_OVERLAY_DIRS`.
  `src/iagent/content_kinds.py` reads it and FAILS CLOSED on an unreadable registry, so it names
  only a directory that exists in the image.
- **`templates/configmap.yaml` gains `SYSTEMS_OF_RECORD_OVERLAY_DIRS`** (default
  `/app/policy/overlays/sample/systems_of_record`, an existing EMPTY directory), read by
  `src/iagent/origin_resolver.py`, which fails closed in the same way. The sandbox declares no
  system of record, so every drop's origin resolves to a miss: dropper/owner-only visibility,
  unchanged.
- Both keys yield to an explicit `agentFleet.env` entry (`hasKey` guard), as the neighbouring
  overlay keys do.

## 0.4.27 — 2026-10-03

Patch bump. Both halves of the 2026-10-02 architect ruling ("Topaz manifest hook +
program_member hook, both before grant sync") now ship: the schema load and the audience fold.

### Changed

- **New `templates/topaz-manifest-load-job.yaml`**, gated by `topazManifestLoad.enabled`
  (off in base, on in sandbox), a post-install/post-upgrade helm hook Job at weight "2" —
  strictly before the task-grant Job's weight "3" — that loads the chart-shipped Topaz ReBAC
  manifest (`topaz-configmap.yaml`'s `manifest.yaml`) via the new `policy/sync/load_manifest.py`.
  A manifest `set` REPLACES THE WHOLE SCHEMA, so the script fail-closed PRE-CHECKS (via the new
  `TopazClient.get_manifest()`) that the live directory declares no type the file does not
  (else nothing loads), then loads, then READS BACK that every file type is present. Closes the
  gap where `templates/task-grant-sync-job.yaml`'s `program_member_sync` leg (below) could die
  E20026 "unknown type" on a cluster where nobody had hand-run `topaz ds set manifest` for a
  recently-added type.
- **`templates/task-grant-sync-job.yaml` now runs `policy/sync/program_member_sync.py` as its
  FIRST leg, before `task_grant_sync.py`**, in the same Job/container. `program_member_sync`
  writes the `program` `member` relations the origin-entitlement ruling reads and was, until
  now, hand-run against every cluster. configMap/git overlay modes copy `program_members.yaml`
  beside `task_grants.yaml` with the same fail-closed FATAL if missing (no fallback to the
  image's sandbox copy); image mode reads it from `/app/policy/program_members.yaml`. No new
  values key — it shares `taskGrantSync.enabled`.

## 0.4.26 — 2026-10-02

Patch bump for chart content that merged without one.

### Changed

- **`TASK_KIND_OVERLAY_DIRS` default gains `/app/policy/overlays/openddil-lab/task_kinds`**
  (`templates/configmap.yaml`, lane/74 `fc3098f2`, merged in `57ae5cab`). The maintenance fault
  workflow's task kinds load from the openddil-lab overlay beside the sample overlay. The change
  merged after 0.4.25 was cut, so two chart contents shared one version number until this bump.
  As before, an explicit `agentFleet.env.TASK_KIND_OVERLAY_DIRS` still overrides the default.

## 0.4.23 — 2026-10-02

Patch bump, chart item before roll #16. Resource limits + a spread preference for the
stateful-core group.

### Added / Changed

- **Resource requests/limits on Keycloak, Restate, Weaviate** (Chart item before roll #16).
  Numbers are set from ONE `kubectl top` sample taken during a substrate prime on 2026-10-02,
  not a sustained profile:
  - `keycloak`: was running with NO resources block at all (17m CPU / 805Mi observed). The
    `keycloak.resources` key already existed in values.yaml but `templates/keycloak.yaml`'s
    container never read it, so it was dead config; now requests cpu 100m / memory 1Gi, limits
    cpu 1 / memory 1536Mi, and the container actually consumes it. No `JAVA_OPTS` / `-Xmx` /
    `MaxRAMPercentage` is set anywhere for keycloak in this chart, so there is no fixed heap
    bound to compare against the new memory limit.
  - `weaviate`: was running with NO resources block at all (96m CPU / 184Mi observed); now
    requests cpu 100m / memory 256Mi, limits cpu 1 / memory 1Gi.
  - `restate`: requests unchanged (250m / 256Mi); memory limit raised 512Mi -> 1Gi (it was
    observed at 114m / 372Mi, 73% of the old limit).
  - `minio` (`iagent-minio`) is **deployed externally to this chart** — a separate manifest, not
    a chart dependency (see the `minioBucketInit` comment block in values.yaml) — so it has no
    pod template here to carry limits or affinity. Its numbers are unchanged because this chart
    does not set them at all; out of scope for this change.
- **`iagent.io/spread-group: stateful-core` pod-template label + a preferred pod anti-affinity**
  on Keycloak, Restate and Weaviate (MinIO excluded for the reason above), toggled by
  `global.statefulSpread.enabled` (default `true`) with weight `global.statefulSpread.weight`
  (default `100`). **Deliberately `preferredDuringSchedulingIgnoredDuringExecution`, never
  `requiredDuringSchedulingIgnoredDuringExecution`**: all four of these components' PVCs are
  `storageClass: local-path`, and all four observed PVs are pinned to the SAME node — `local-path`
  has no cross-node migration, so a REQUIRED anti-affinity on this label would leave every pod
  after the first permanently `Pending`, asking the scheduler to avoid the only node any of them
  can actually run on. This changes **nothing about where pods land today** while every PV stays
  pinned to that one node; it only takes effect once those volumes are migrated off `local-path`
  onto something that isn't node-pinned — a separate decision, not made here. The label is added
  to pod template metadata only, never to a StatefulSet's `spec.selector.matchLabels` (selectors
  are immutable; changing one breaks `helm upgrade` on an existing release).

## 0.4.22 — 2026-10-02

Minor bump. The Topaz manifest gains a seventh namespace for the origin-entitlement
ruling (architect, 2026-10-02): program membership.

### Added

- **`program` object type** (`relations: member: user | group#member`,
  `permissions: can_view_program: member`). A viewer may read an artifact by its
  recorded ORIGIN — never by audience — iff their domain role can_consume the
  origin's owner_domain (`policy/domain_consumption.yaml`, evaluated in-process) AND
  they can_view_program the origin's recorded program (this new relation,
  git-asserted in `policy/program_members.yaml`, synced by
  `policy/sync/program_member_sync.py`). The resolver that SETS an artifact's origin
  is a separate, not-yet-shipped piece; an artifact with no recorded origin is
  unaffected and stays visible to its dropper/owner only, today's behaviour.

## 0.3.22 — 2026-07-20

Patch bump. In-cluster service URLs default to the FQDN form so a
corporate proxy can't intercept them.

### Fix

- **`svcDomain` defaults to `.<release-ns>.svc.cluster.local` instead of
  empty.** The helper returned `global.clusterDomain | default ""`, so
  whenever that value was unset every service URL rendered BARE
  (`<release>-engine-a:8081`). A bare name has no dots and therefore does
  NOT suffix-match a `NO_PROXY` entry of `.svc` / `.svc.cluster.local`, so
  under a corporate proxy the in-cluster call is handed to the proxy and
  fails (`ProxyError: Unable to connect to proxy`). This broke the
  supervisor's verb dispatch: engines registered a bare `endpoint_url`, so
  the specialist call was proxied, `execute_subtask` failed, and the
  cascade left no UI payload and a blank answer card — while routing
  itself looked perfectly healthy. The `dagsterUrl` helper already
  hardcoded the FQDN for this exact reason; `svcDomain` now matches it.
  `global.clusterDomain` remains an override for non-`cluster.local`
  domains.

  **Operators must rollout-restart the engines after upgrading** —
  `endpoint_url` is baked into the verb edge at registration time, so
  existing edges keep the bare form until re-registration overwrites them.

## 0.3.21 — 2026-07-18

Minor bump. The substrate wipe no longer breaks answer delivery, and a
consistent scorched-earth option is added.

### Fix

- **Default `--wipe` is routing-substrate only; preserves user data.**
  The prime wipe was a blanket `MATCH (n) DETACH DELETE n` that deleted
  the answer-durability graph including `WatermarkSequence` — resetting
  the monotonic answer-watermark sequence to 1 while the projector's
  Postgres cursor stayed parked at its old high value. Every new answer
  then landed *below* the cursor and never projected to the UI: the run
  completed, the progress card showed, but no answer appeared and it
  vanished on refresh (observed at work 2026-07-18). The default wipe now
  clears only `OntologyClass` (+ its verb/subClassOf edges), Weaviate
  collections, Jena graphs, and MinIO TTLs — the reproducible routing
  substrate — and **preserves** `AnswerArtifact`/`Actor`/`Source`/
  `WatermarkSequence` plus the Postgres projections. A wipe+reprime can no
  longer strand the projector or delete answer history.

### Add

- **`primeSubstrate.nuclear`** (default `false`). When set with `wipe`,
  escalates to a full scorched-earth: blanket Neo4j `DETACH DELETE` AND a
  reset of the derived Postgres stores (`answer_artifact_projection` /
  `human_task_projection` truncated, `projector_cursor` rewound to 0) in
  the same pass — source and projection reset *together*, so even a
  nuclear wipe never leaves a stranded cursor. The Job wires
  `PROJECTOR_POSTGRES_DSN` (same template the projector uses) so the reset
  can reach Postgres; the script RAISES if it can't, refusing to report a
  partial nuclear as clean.

## 0.3.20 — 2026-07-18

Patch bump. The self-healing reregister hook now restarts the Data
Analyst engine too.

### Fix

- **Data Analyst added to the reregister restart set.** The
  `primeSubstrate.reregisterEngines.deployments` list restarted
  `engine-a/d/e/w/f` but omitted `data-analyst`, which self-registers
  `mesh:analyzeDataset` on startup. After a wipe+reprime the other
  catalog verbs came back (their engines were in the list) but
  `analyzeDataset` did not — the class graph showed 8 of 9 verbs on
  `idp:Dataset`. Now restarted with the rest so re-registration is
  complete. Verb edges are runtime state; only an engine restart
  rebuilds them.

## 0.3.19 — 2026-07-18

Patch bump. Engines now advertise REACHABLE self-endpoints at any
release name.

### Fix

- **Engine self-advertisement URLs are release-aware.** Each engine
  bakes an endpoint into its own verb registration, read from
  `ENGINE_A_PUBLIC_URL` / `DATAHUB_WRAPPER_SVC_URL` /
  `ENGINE_E_PUBLIC_URL` / `ENGINE_E_RESOLVE_INSTANCE_URL` /
  `ENGINE_E_RESOLVE_DMC_URL` / `ENGINE_W_PUBLIC_URL` /
  `ENGINE_DA_PUBLIC_URL` — env vars the chart never set, so they fell
  to hardcoded SANDBOX defaults (`http://iagent-engine-*`). At a
  release NOT named `iagent` (e.g. work's `invincible-agent`) those
  hosts don't resolve, so every registered verb / `mesh:resolveInstance`
  provider endpoint pointed at a nonexistent host (`Name or service not
  known`): routing resolved the subject and found the verb, then
  couldn't call it. These are a DISTINCT var set from the `*_SVC_URL`
  vars (how OTHER services reach each engine, already release-aware) —
  the self-advertisement half was missing. Now published release-aware
  in the shared ConfigMap. **Rollout-restart the engines after upgrade**
  so they re-register with the corrected URLs (the sandbox-named
  endpoints are baked into existing Neo4j edges / Weaviate rows until
  re-registration overwrites them).

## 0.3.18 — 2026-07-17

Patch bump. Wipe+reprime becomes self-healing: `primeSubstrate.wipe`
clears both TTL-owned state (OntologyClass nodes + subClassOf edges) and
runtime-owned state (engine verb edges), but only the ingest rebuilt the
former — the verb edges stayed gone until someone manually restarted the
engines, and a class graph with zero verbs routes silently to the
generalist with no error.

### Add

- **`primeSubstrate.reregisterEngines`** (default `enabled: true`) — a
  companion post-hook (weight = `primeSubstrate.hook.weight` + 10, so it
  runs after prime completes) that WAITS for the ingest sentinel node in
  Neo4j (`idp:Dataset` by default — prime fire-and-forgets the async
  ingest, so a naive restart would race an empty graph and the
  re-registering engines would Contract-D-reject), then rolling-restarts
  the registering engine deployments (A/D/E/W/F; Engine O excluded as the
  registry consumer) via the in-cluster K8s API — the same mechanism as
  `kubectl rollout restart`. Reuses the prime image (has `neo4j` +
  `requests`), so no new image to mirror; ships minimal namespaced RBAC
  (patch deployments in the release namespace only). Sentinel timeout is
  best-effort, not fatal — the DataHub→doc-tools sensor path self-heals
  registration via retries once the classes land. Set `enabled: false`
  to opt out.

## 0.3.17 — 2026-07-17

Patch bump. mesh-registrar gets the release Secret.

### Fix

- **mesh-registrar `envFrom` the full `<release>-secrets`**, like every
  engine pod. It previously received ONLY a lone `DATAHUB_TOKEN`
  secretKeyRef, so: (a) Predicate-row EMBEDDINGS ran keyless —
  `utils/embed.py` (`LLM_API_KEY`/`OPENAI_API_KEY`) fell back to
  `"any"`, and against an auth-enforcing gateway the embed call failed,
  which the registrar fail-softs by writing rows WITHOUT vectors:
  registration looked green while semantic verb search silently
  degraded; (b) Neo4j writes fell back to `main.py`'s hardcoded
  sandbox-default password — auth failure on any deployment with a
  real password (e.g. an external neo4j at work), now that 0.3.16
  derives the fleet `NEO4J_PASSWORD` into the Secret. Embedding config
  is the same fleet-wide trio everything else uses:
  `secrets.openaiApiKey` (or `agentFleet.secrets.LLM_API_KEY`) +
  `agentFleet.env.OPENAI_BASE_URL`/`LLM_BASE_URL` +
  `agentFleet.env.LLM_EMBED_MODEL` (default `nomic-embed-text`).

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
