# One realm, many instances: the identity prefix

**Status: PROPOSED, 2026-11-20. Nothing is built.** This is for the architect to rule on. It is a
requirement for a later release, not for 0.4.91. The census in §4 was read from master `91305a37`.
Revised after gov's review of #482, which found the census complete. Gov's four notes for the
ruling are folded in where they apply: §1 (role stems), §2 (cutover and the central gateway's
posture), §5 (the base render) and §6 Q1.

**The requirement.** A deployment runs one instance of this chart per use: development, test and
production. All the instances use one shared identity provider (one realm). The chart has to support
that, and a token issued for one instance must be refused by every other instance.

## 0. The proposal in brief

1. **One value, `identity.prefix`, empty by default.** Every client id becomes the prefix followed
   by a role literal: `<prefix>iagent-engine-o`, `<prefix>cortex-ui`, and so on. The role literal
   stays in code and in the chart, where it can be audited. Only the prefix comes from
   configuration, and it is applied in **exactly three places**:
   - (a) the mint helpers, for outbound tokens;
   - (b) the readers that compare a token's `azp`, for inbound checks;
   - (c) the chart, which renders the names the identity provider and the browser see.
2. **The audience is derived, never typed.** It is `AUD = <prefix> + "cortex-bff"`. The BFF, the
   engines, the registrar and the central gateway each accept exactly `[AUD]`. Every instance's
   `audience-bff` mapper stamps exactly `AUD`. The free-form values `acceptedAudiences` and
   `realmAudience` are retired. With an empty prefix, `AUD` is `cortex-bff`, which is what the one
   overlay that sets an audience already uses, so **that overlay's render does not change.**
3. **Policy and directory are per instance.** Each instance has its own Topaz instance, its own
   directory, its own policy rail and its own seed reference. Instances share only what lives in
   the realm: people, brokers, signing keys and realm settings. §3 lists both sides, and names one
   hazard (two releases writing the same realm objects) that needs a ruling.
4. **The census (§4)** lists every literal client id and audience in the code, the charts, the
   scripts, the examples and the sibling repositories.

## 1. The prefix, and how a client id is composed

### The value

```yaml
identity:
  # Empty: one instance owns the realm's names (today's behaviour). When non-empty, it is
  # prepended to every client id and to the audience, and it must match ^[a-z][a-z0-9]{0,11}-$:
  # lower-case, at most 12 characters before a single trailing hyphen, and no hyphen inside.
  prefix: ""
```

- **No hyphen inside the prefix.** Then no prefix is the start of another, and the `azp` check
  in (b) below cannot confuse one instance with another.
- **The pattern alone is not enough (gov, on #482).** It admits the role stems `iagent-` and
  `cortex-`, which begin every role literal. Such a prefix breaks two things:
  - the double-prefix refusal below refuses every mint, because every role literal already
    starts with that prefix;
  - the optional `azp`-prefix check (§2) admits a co-tenant that uses the empty prefix, because
    `iagent-engine-o` starts with `iagent-`.

  **Proposed:** the chart and the composing function also refuse any prefix that is the start of a
  role literal. That rule is checked against the role literals themselves, not against a typed
  list of stems, so a new stem is covered when it is added. §6 Q1 settles this before anything is
  built.
- **The chart refuses to render** a prefix that does not match the pattern or that fails the
  role-stem rule.
- **The shared ConfigMap exports the prefix to every pod** as `IAGENT_IDENTITY_PREFIX`. One key
  reaches every workload that loads that ConfigMap, the BFF and Dagster included.

### The rule: role names everywhere, the prefix in one place per surface

Today a client id appears as a code literal, as a values entry and as an environment default
(§4). If each of those carried the full, prefixed name, each would be a place where one instance
could name another instance's client. Instead:

- **Code keeps the role literal at the call site.**
  - For example, `engine_mint(client_id="iagent-engine-o", …)` is unchanged.
  - The surfaces are `engine_mint` (`agent_fleet/utils/mesh_registration.py:119`), its engine A
    sibling (same signature), `service_identity.mint_service_token`, the case-runner mint, and
    `agent_routers`' supervisor mint.
  - Each of them composes `prefix + role` immediately before it calls the SDK's
    `mint_token(client_id=…)`. The SDK is unchanged, because it already takes the full id as an
    argument.
  - **The composing function is one function, imported by both trees through one module path.** A
    dual import would create two module objects, and the two could disagree.
- **Environment variables carry the role name.**
  - The variables are `REVIEW_STARTER_CLIENT_ID`, `CORTEX_CLIENT_ID`, `SUPERVISOR_CLIENT_ID`,
    `CASE_RUNNER_CLIENT_ID`, `GRAPH_HOST_CLIENT_ID` and `IDENTITY_EXCHANGE_CLIENT_ID`.
  - The code still prefixes them. So an override in `agentFleet.env` cannot leave the instance's
    namespace: a value naming another instance's full client id becomes
    `<prefix><other-prefix>iagent-…`. No such client exists, so the mint fails.
- **A role name that already starts with the instance's prefix is refused,** with an error that
  names it. This stops an id from being prefixed twice, and the refusal is loud. It applies only
  when the prefix is non-empty.
- **Inbound `azp` comparisons prefix the role names they read.**
  - Today the only one is `CAN_CALL_DOOR_CLIENTS` (`src/iagent/authz/call_capability.py:52–58`).
    No values file sets it yet.
  - It stays a list of role names, and the reader compares `azp` against `prefix + role`.
  - **This matters for safety, not only for tidiness.** A door caller whose `azp` is not
    recognised as a door is treated as an ordinary caller. If the list carried unprefixed names in
    a prefixed instance, the door's narrowing would silently not apply. Deriving the name in the
    reader closes that.
- **The chart renders the full names wherever the provider or the browser sees them.** That
  covers:
  - the client list (`keycloak.serviceClients`, `extraServiceClients` and `publicClients`);
  - the `cortex-ui` client in the realm import and in the reconcile job;
  - the `cortex-ui` collision check in `_helpers.tpl`;
  - `cortexUi.env.VITE_KEYCLOAK_CLIENT_ID`;
  - the `iagent-mesh-mcp` chart's `client.clientId`.

  Each of these keeps its role literal in the template or the values, and a single helper,
  `invincible-agent.clientId`, prepends the prefix.

### Where the prefix does not apply

- **`svc:` authz ids** (`authzId: "svc:engine-o"`, the `authz-id-svc` hardcoded claim):
  - They stay unprefixed and are identical in every instance.
  - This is safe because a `svc:` identity is resolved only by its own instance's Topaz (§3), and
    the audience (§2) stops its token from reaching another instance.
  - **The cost:** a log line or audit record that shows only `svc:engine-o` does not say which
    instance it came from. Where that matters, the record also carries `azp`. The BFF already
    records `via=azp` (`src/iagent/gateway.py:8633`, `:12721`).
- **Delegate rows on the policy rail** (`policy/gateway_delegates.yaml`, `queue_delegates.yaml`)
  key on the `svc:` id, so they are unchanged. The chart's delegate *client* rows
  (`extraServiceClients` with `kind: delegate`) carry a client id, so their `clientId` takes the
  prefix like every other client. Their `onBehalfOf.user` names a realm user, which is shared
  (§3), so it is unchanged.
- **Kubernetes names** (Services, Secrets, ConfigMaps, and in-cluster URLs such as
  `http://iagent-engine-e:8086`):
  - These are namespaced. One instance per release and namespace keeps them apart already, so
    they are out of scope.
  - Each instance's client secrets live in its own namespace. That is the **second separator**:
    a pod that names another instance's client does not hold that client's secret, so its mint
    fails with a 401.

### Composition, by example (illustrative prefixes)

| role literal (stays in code) | prefix `""` | prefix `d-` | prefix `p-` |
| --- | --- | --- | --- |
| `iagent-engine-o` | `iagent-engine-o` | `d-iagent-engine-o` | `p-iagent-engine-o` |
| `cortex-ui` | `cortex-ui` | `d-cortex-ui` | `p-cortex-ui` |
| `iagent-mesh` (mesh-mcp chart) | `iagent-mesh` | `d-iagent-mesh` | `p-iagent-mesh` |
| audience `cortex-bff` | `cortex-bff` | `d-cortex-bff` | `p-cortex-bff` |
| `svc:engine-o` (authz id) | unchanged | unchanged | unchanged |

**Recommendation, for the ruling:** in a realm that is shared, every instance sets a **non-empty**
prefix. The empty prefix stays the default for a deployment that owns its realm. Otherwise the
instance with the empty prefix owns the bare names, and any instance that loses its prefix value
falls back onto that instance's names. The mint would still fail, because the secret is not there,
but the failure would read as the wrong instance's 401.

## 2. The audience is per instance

### Derivation

`AUD = identity.prefix + "cortex-bff"`. The role literal `cortex-bff` sits in one chart helper,
`invincible-agent.audience`.

| consumer | today (master) | proposed |
| --- | --- | --- |
| BFF `BFF_JWT_ACCEPTED_AUDIENCES` (`frontend.yaml:179–180`, read at `src/iagent/auth.py:202,253`) | `acceptedList` of `cortexBff.auth.acceptedAudiences` | `AUD` |
| engines `MESH_JWT_ACCEPTED_AUDIENCES` (`_helpers.tpl` `engineTokenEnv`; `engines.yaml`) | the same list | `AUD` |
| mesh-registrar (`mesh-registrar.yaml`, `engineTokenEnv`) | the same list | `AUD` |
| central gateway `GATEWAY_JWT_AUDIENCES` (`_helpers.tpl` `gatewayTokenEnv`, 838–860) | the same list | `AUD` |
| `audience-bff` mapper on `cortex-ui` and every service client (`keycloak-configmap.yaml:155–159, 265–269`; `realm-reconcile-job.yaml:142, 420–438, 772–782, 931`) | `included.custom.audience` = `realmAudience` | `AUD` |
| `audience-self` mapper on each public client (`keycloak-configmap.yaml:210–214`; `realm-reconcile-job.yaml:484, 503, 905`) | the client's own id | the client's own **prefixed** id (follows from §1) |
| mesh-mcp chart `client.exchangeAudience` (required, no default; `keycloak-client-job.yaml:4, 124`) | typed per deployment | `AUD`, from the same prefix value |

- **All four accepted lists already come from one helper** (`invincible-agent.acceptedList`). So
  the change is to that helper and to the two mapper sites, not to each consumer.
- **`acceptedAudiences` and `realmAudience` are retired.**
  - For one release they stay as guards: the render fails if either is set to anything other than
    `[AUD]` or `AUD`.
  - After that release they are removed.
  - The guard in `frontend.yaml:67–68` (`realmAudience` must be in `acceptedAudiences`) becomes
    true by construction, so it goes.
- **An instance accepts exactly one audience. There is no extra-audience key.** An instance that
  could accept a second audience could accept another instance's audience, which is the thing
  the requirement forbids.
  - A cutover from today's names to prefixed ones is a single roll: access tokens are
    short-lived, and the mapper and the accepted list change in the same release.
  - **A deployment's own private overlay can hit the retirement guard (gov, on #482).** An overlay
    that sets `acceptedAudiences` or `realmAudience` to anything other than the derived `AUD`
    fails to render on the release that adds the guard.
    - The cutover note in the CHANGELOG tells such deployments to render with `--dry-run`
      against their own overlay before they upgrade.
    - A deployment whose audience today is not `<prefix>cortex-bff` cannot keep that audience.
      Its tokens change audience in that release, and that is a consequence of the ruling, not a
      side effect.
  - **For the ruling:** if a transition window is wanted, it should be a dated, single-release
    key that the render refuses after its date, not an open list.

### What deny-by-default rests on afterwards

- **Today, an empty audience list refuses every token.** Under the proposal the audience list is
  never empty, because `AUD` is always derived. **Deny-by-default is kept by
  `acceptedIssuers: []`, which still refuses every token** (`src/iagent/auth.py:248–257`).
  - Gov checked all three verifiers on #482: the BFF, the SDK and the central gateway.
  - **"The base chart is closed" holds for the BFF and the engines only.** The central gateway's
    base posture is `observe`, so in the base chart it does not refuse.
- **Instances that share a realm share one issuer,** so the issuer no longer separates them.
  Separation rests on three things, in order:
  1. **The audience.** One instance's mapper never stamps another instance's `AUD`.
  2. **The client secret.** It lives in each instance's own namespace.
  3. **The `azp` (optional, for the ruling).** Each verifier could also require that `azp` starts
     with its own prefix.
     - This defends against a realm administrator adding a mapper that stamps the wrong audience
       onto a client.
     - It means nothing when the prefix is empty, and it is cheap in the BFF.
     - In the engines it is an SDK change (`iagent-mesh-sdk`), so it would be a later step.
     - **Recommendation:** the BFF in the same release, the SDK later.
- **One provider behaviour to rule out:** Keycloak's *audience resolve* mapper adds to `aud` the
  ids of clients whose client roles appear in a token.
  - Every accepted audience is a custom string (`included.custom.audience`), not a client. So
    this cannot add another instance's `AUD`, **as long as no client is ever named
    `<prefix>cortex-bff`.**
  - The render's collision check should refuse a client id equal to any `AUD` shape (an id that
    ends in `cortex-bff`).

## 3. Policy and directory data are per instance

### Per instance (one copy for each instance)

- **Topaz:** each release runs its own (`topaz-service.yaml`, `topaz-configmap.yaml`).
- **Its directory:** the projection of `policy/users.yaml`, `groups.yaml`, `personas.yaml`,
  `program_members.yaml` and the overlays.
- **Its policy rail:** `capability_grants`, `asset_grants`, `task_grants`, `gateway_delegates`,
  `queue_delegates`, the canvases and the measures.
- **Each instance's seed** (`topaz-seed-cronjob.yaml`, `topaz-manifest-load-job.yaml`,
  `task-grant-sync-job.yaml`) reads from **its own** seed reference.
  - Two instances that point at one reference share policy because a person chose to point them
    there, not because the mechanism shares it.
  - **Recommendation:** one reference per instance (a branch or a path in the policy repository),
    so a grant reaches production only by being merged into production's reference.
- **Every client,** with its secret, its mappers (`audience-bff`, `audience-self`, the
  `authz-id-svc` hardcoded claim, and the `cortex-ui` authz-attribute mapper), its redirect set and
  its client roles.
- **The audience (§2).**
- **Everything else the release already owns:** Postgres projections, Restate, Dagster and the
  stores. This is unchanged.

### Shared (realm-scoped, one copy for every instance)

- **The realm itself:** its issuer, its signing keys, and its token and session settings.
  `acceptedIssuers` is therefore identical across instances.
- **People.** Each user, with their attributes, exists once.
  - That includes the authz-id attribute, so **a person's authz id is the same in every instance.**
  - What the person may do is decided separately by each instance's Topaz.
  - A person appears in an instance's directory only if that instance's policy lists them.
- **Identity-provider brokers,** their mappers (sub to authz id, username), and the first-login
  flow.
- **The user-profile attribute policy.**
- **Non-interactive users:** the persons a delegate client may name in `onBehalfOf`. They are
  realm users, so they are shared, even though the delegate *clients* that name them are per
  instance.
- **Realm roles, realm groups and realm-level client scopes,** if any are used. This chart's
  authorization does not read them: groups come from the policy rail, not from the token.

### The hazard: two releases write the same realm objects

The reconcile job (`realm-reconcile-job.yaml`) writes these realm-scoped objects as well as its own
clients:

- the local humans and the declared users (`$API/users`, around 276–557);
- retired users (557);
- the user-profile policy (296);
- the identity-provider brokers and their mappers (577–669);
- the first-login flow (607).

If two instances share a realm, each instance's reconcile job writes all of these. The result is:

- **the last writer wins;**
- **one instance's values can change another instance's people.** For example, a user retired in
  test's values is disabled everywhere.

**Proposed:** add `keycloak.realmObjects: managed | external`, with `managed` as the default (that
is, today).

- In `external` mode the job writes only this instance's prefixed clients and their mappers. It
  reads and verifies the realm objects it depends on, and fails naming any that are missing.
- In a shared realm, every instance runs `external` except at most one *realm-owner* release. It
  is equally valid for the realm to be managed outside the chart, with every instance `external`.

**For the ruling:** should a non-empty prefix with `managed` refuse to render, or only warn?
Lane 1 recommends **refuse**, with an explicit `realmOwner: true` to allow it. Then becoming the
release that edits everyone's people is a decision someone wrote down, not a default someone
inherited.

## 4. Census: every literal client id and audience today (master `91305a37`)

### 4a. Code that mints with a client id literal (outbound)

The role literal is passed to `engine_mint`, or to the engine A helper with the same signature.
**Under the proposal these call sites are unchanged; the helper adds the prefix.**

| file | lines | literal |
| --- | --- | --- |
| `agent_fleet/cost_agent/main.py` | 259 | `iagent-cost-agent` |
| `agent_fleet/data_analyst/main.py` | 158 | `iagent-data-analyst` |
| `agent_fleet/datahub_wrapper/main.py` | 663 | `iagent-engine-d` |
| `agent_fleet/docs_agent/main.py` | 205 | `iagent-docs-agent` |
| `agent_fleet/finance_agent/main.py` | 638 | `iagent-finance-agent` |
| `agent_fleet/neo4j_expert/main.py` | 66, 127, 196, 247, 303 | `iagent-engine-e` |
| `agent_fleet/ontology_service/main.py` | 909, 952, 1013 | `iagent-engine-o` |
| `agent_fleet/planning_agent/main.py` | 145 | `iagent-planning-agent` |
| `agent_fleet/safety_agent/main.py` | 394 | `iagent-safety-agent` |
| `agent_fleet/weaviate_expert/main.py` | 45, 83, 146, 253, 296 | `iagent-engine-w` |
| `agent_fleet/restate_analyst/main.py` | 697, 3646, 3669, 3707, 3732, 3755, 3778, 3807, 3869, 3906, 3945, 3984, 4025, 4070, 4125 | `iagent-engine-a` |
| `agent_fleet/restate_analyst/policy_rules_client.py` | 88 | `iagent-engine-a` |
| `agent_fleet/restate_analyst/review_composer.py` | 125 | `iagent-engine-a` |
| `agent_fleet/restate_analyst/spo_interview.py` | 128, 174, 207 | `iagent-engine-a` |
| `agent_fleet/restate_analyst/spo_step_executor.py` | 155 | `iagent-engine-a` |

### 4b. Code that reads a client id from the environment, with or without a literal default

| file | line | variable | default |
| --- | --- | --- | --- |
| `agent_fleet/graph_host/main.py` | 428 | `GRAPH_HOST_CLIENT_ID` | `iagent-graph-host` |
| `src/iagent/defs/agent_routers.py` | 124, 285 | `SUPERVISOR_CLIENT_ID` | `iagent-supervisor` |
| `agent_fleet/restate_analyst/dispatch_driver.py` | 288 | `REVIEW_STARTER_CLIENT_ID` | none |
| `agent_fleet/utils/service_identity.py` | 135 (`mint_service_token`) | `REVIEW_STARTER_CLIENT_ID` | none |
| `src/iagent/defs/extraction_review_sensor.py` | 387 (`mint_service_token`, a thin wrapper) | `REVIEW_STARTER_CLIENT_ID` | none |
| `agent_fleet/utils/service_identity.py` | the case-runner mint | `CASE_RUNNER_CLIENT_ID` | none |
| `src/iagent/identity_exchange.py` | 51 | `IDENTITY_EXCHANGE_CLIENT_ID` | none |

### 4c. Code that compares against a client id or an audience (inbound)

| file | line | what |
| --- | --- | --- |
| `src/iagent/authz/call_capability.py` | 52–58 | `CAN_CALL_DOOR_CLIENTS`, an `azp` allow-list. **No literal, and no values file sets it yet.** |
| `src/iagent/auth.py` | 202, 248–265 | `BFF_JWT_ACCEPTED_AUDIENCES`. **No literal.** It reads the served list and refuses if the list is empty. |
| `src/iagent/gateway.py` | 8633, 12721 | records `via=azp` (a client id, used for audit). **No literal.** |

The engines' and the registrar's audience check is in `iagent-mesh-sdk`. It reads
`MESH_JWT_ACCEPTED_AUDIENCES` and has no literal.

### 4d. The `invincible-agent` chart: client ids

| file | lines | what |
| --- | --- | --- |
| `templates/configmap.yaml` | 351, 366, 373, 381 | env defaults: `REVIEW_STARTER_CLIENT_ID` `iagent-review-starter`, `CORTEX_CLIENT_ID` `iagent-data-analyst`, `SUPERVISOR_CLIENT_ID` `iagent-supervisor`, `CASE_RUNNER_CLIENT_ID` `iagent-case-runner` (each `hasKey`-guarded, so `agentFleet.env` can override it) |
| `values.yaml` | 2368–2477 | `keycloak.serviceClients`: `iagent-engine-d`, `-engine-e`, `-engine-o`, `-engine-w`, `-review-starter`, `-data-analyst`, `-supervisor`, `-engine-a`, `-doc-tools`, `-planning-agent`, `-finance-agent`, `-safety-agent`, `-docs-agent`, `-cost-agent`, `-graph-host` |
| `values.yaml` | 2487 | `extraServiceClients: []` |
| the environment overlay (`values-<env>.yaml`) | 561–587 | two `extraServiceClients` delegate rows: an external delegate client, and `iagent-case-runner` |
| `values.yaml` | 2210; overlay 489–492 | `publicClients: []`. The overlay declares one public client (`training-workbench`), which takes the prefix and whose `audience-self` follows it. |
| the overlay | 528 | a broker's `clientId`, which is **the id registered at the upstream provider, not a client in this realm**. A broker is realm-scoped and shared (§3), so this id is **not** prefixed. |
| `values.yaml` | 1867; overlay 764 | `cortexUi.env.VITE_KEYCLOAK_CLIENT_ID: "cortex-ui"` |
| `templates/keycloak-configmap.yaml` | 125 | the `cortex-ui` client, as a hard literal |
| `templates/keycloak-configmap.yaml` | 42, 60, 75, 90, 105, 120 | `clientRoles: {"cortex-ui": …}` on users in the realm import |
| `templates/realm-reconcile-job.yaml` | 333, 362, 421, 713, 735, 772 | `clients?clientId=cortex-ui`, as a hard literal |
| `templates/realm-reconcile-job.yaml` | 149, 444, 697, 844, 876, 934 | `$c.clientId` / `$pc.clientId`, from values |
| `templates/_helpers.tpl` | 260 | the public-client collision check against the literal `cortex-ui` |
| `templates/_helpers.tpl` | 930 | the realm-import client body, `$c.clientId` |

Doc-tools' client (`iagent-doc-tools`) is created here because the realm is managed here, and
consumed by doc-tools' own chart. That chart needs the same prefix value.

### 4e. The `invincible-agent` chart: audiences

| file | lines | what |
| --- | --- | --- |
| `values.yaml` | 1972–1974 | `cortexBff.auth.acceptedIssuers: []`, `acceptedAudiences: []`, `realmAudience: ""` |
| the environment overlay | 842–844 | `acceptedAudiences: [cortex-bff]`, `realmAudience: cortex-bff`. **This is the only audience literal in any values file.** |
| `templates/_helpers.tpl` | 824–876 | `acceptedList`, `gatewayTokenEnv` and `engineTokenEnv` pipe the one list to the BFF, the gateway, the engines and the registrar |
| `templates/frontend.yaml` | 67–68, 179–180 | the `realmAudience ∈ acceptedAudiences` guard; `BFF_JWT_ACCEPTED_AUDIENCES` |
| `templates/keycloak-configmap.yaml` | 4, 155–159, 210–214, 265–269 | `audience-bff` (custom audience from `realmAudience`); `audience-self` (each public client's own id) |
| `templates/realm-reconcile-job.yaml` | 142, 420–438, 484, 495, 503, 772–782, 905–908, 931 | the same two mappers, repaired and verified |

### 4f. The `iagent-mesh-mcp` chart

| file | line | what |
| --- | --- | --- |
| `values.yaml` | 18 | `client.clientId: "iagent-mesh"` |
| `values.yaml` | 25 | `client.exchangeAudience: ""` (required, no default) |
| `templates/keycloak-client-job.yaml` | 4, 55–56, 106–124 | `audience-self` (own id) and `audience-exchange` (the exchange audience) |

### 4g. Scripts, probes and examples

| file | line | literal |
| --- | --- | --- |
| `scripts/mint_persona_token.py` | 36 | `_CLIENT = "cortex-ui"` |
| `scripts/walk_census.py` | 76 | `KC_CLIENT_ID`, default `cortex-ui` |
| `scripts/probes/require_matrix.py` | 38 | a client-credentials request. Its client id comes from its caller. |
| `examples/keycloak_data/realm-export.json` | 22, 30, 43 | `cortex-ui`, `iagent-review-starter` (local development; stays unprefixed) |

### 4h. Tests, and the other repositories

- **227 test files** name a client id, `cortex-ui` or `cortex-bff`. Many of these name the BFF as
  a service, not as an audience.
  - With an empty prefix none of them changes.
  - The build adds seals for a non-empty prefix (§5).
- **`cortex-ui`** has no literal. It reads `VITE_KEYCLOAK_CLIENT_ID` from its served config
  (cortex-ui `src/auth/AuthProvider.tsx:9`, `src/api/client.ts:51`).
- **`iagent-mesh-sdk`:** `mint_token(client_id=…)` takes the id as an argument, and the verifier
  reads its accepted lists from the environment. Neither has a literal. The optional `azp`-prefix
  check (§2) would be its only change.
- **`doc-tools`** consumes the `iagent-doc-tools` credential (§4d).

**What is not a client id,** despite the same spelling: in-cluster Service URLs such as
`http://iagent-engine-e:8086` and `http://iagent-data-analyst:8089` (configmap, overlay and
values comments); image and deployment names; and the `cortex-ui` and `cortex-bff` consumer names
in the store policy tables.

## 5. If ruled: the build, and the seals it owes

**One PR in this repository,** through gov:

1. The values key and the pattern check.
2. The helpers `invincible-agent.clientId` and `invincible-agent.audience`.
3. The prefixed renders listed in §4d and §4e.
4. The retirement guards for `acceptedAudiences` and `realmAudience`.
5. `IAGENT_IDENTITY_PREFIX` in the shared ConfigMap.
6. The composing function in the mint helpers, and in the `azp` reader.
7. `keycloak.realmObjects`.

The mesh-mcp chart and doc-tools follow with the same value.

**Seals.** Each one names the claim it defends.

- **An empty prefix renders byte-identical to today for every overlay that already sets
  `cortex-bff`,** apart from the retired keys. This is the no-op, measured as one.
  - **The base chart is not a no-op (gov, on #482),** and the seal states its diff exactly
    instead of claiming none.
  - Its accepted-audience variables go from empty to `cortex-bff`.
  - Its `audience-bff` mapper is rendered where today none is, because `realmAudience: ""`
    renders no mapper.
  - The seal pins both differences and nothing else, and the base still refuses every token
    through `acceptedIssuers: []` (§2).
- With prefix `t-`:
  - every rendered client id starts with `t-`;
  - every accepted list is exactly `["t-cortex-bff"]`;
  - every `audience-bff` mapper stamps exactly `t-cortex-bff`;
  - no rendered value contains a bare `cortex-bff` audience.
  - **Each part has a mutation control:** drop the prefix from one site, and the seal fails
    naming that site.
- **The mint composes once.** A role name that already carries the prefix raises. An env override
  that names another prefix yields a client that does not exist.
- **The door list is applied under a prefix:** a `t-` door's `azp` is treated as a door. The
  control is the same list with the prefix not applied, which must fail.
- **A token for the other instance is refused:**
  - the BFF, against `aud=p-cortex-bff` while configured for `t-`;
  - the engines, through the SDK's existing audience check, fed the derived list.
- **`realmObjects: external` writes no realm-scoped object.** The test asserts that the rendered
  job contains no `$API/users`, `identity-provider` or `authentication/flows` write.

## 6. Questions for the ruling

1. **The prefix shape:** `^[a-z][a-z0-9]{0,11}-$`, with the hyphen included in the value. The
   alternative is a bare token with the chart adding the hyphen. **Either way, also refuse a prefix
   that is the start of any role literal** (`iagent-`, `cortex-`; §1). Without that, the
   double-prefix refusal and the `azp`-prefix check both fail. This must be settled before
   anything is built.
2. **In a shared realm, must every instance set a non-empty prefix?** Lane 1 recommends yes; §1
   gives the reason.
3. **A transition audience:** none, or one dated, single-release key (§2)?
4. **The `azp`-prefix check:** in the BFF in the same release, and in the SDK later (§2)?
5. **`realmObjects`:** add the value, and refuse a non-empty prefix with `managed` unless
   `realmOwner: true` (§3)?
6. **One policy seed reference per instance:** a recommendation, or a rule the render enforces
   (§3)?
