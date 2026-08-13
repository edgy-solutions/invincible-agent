# Unminted-caller enumeration — five-repo sweep

> **STATUS: 5 of 5 REPOS SWEPT** — platform, `iagent-mesh-sdk`, `dag-tools`, `doc-tools`,
> `cortex-ui`. **The enumeration is complete.**
>
> `cortex-ui` returned a **structural zero**, written up separately in
> `cortex-ui-transport-idiom`. The method did not transfer there — for a stronger reason than
> "JS is harder to grep": **the category does not exist in that repo.** See REPO 5 below.

## READ THIS FIRST — the classifier was wrong THREE times, in three different ways

This is the section that governs how every row below should be read.

**Three automated passes over one tree produced three different answers, and each was wrong
differently:**

1. **Indirection defeats a string match.** Pass 1 flagged `dynamic_supervisor.py:1037` UNMINTED.
   It is minted — the credential attaches inside `_telemetry_headers(config)`, so searching the
   call block for `Authorization` finds nothing.
2. **Over-resolution drops true positives.** Pass 2 resolved helpers and then reported only ONE
   minted call, losing four that reading confirms are minted. Target regex and window too narrow.
3. **A 20-line window cannot see past a 15-line comment.** Pass 3 reported nine callers
   "RAISES, uncaught" and three "unchecked — body used as result". **Both were false.** These
   call sites carry long explanatory comments between the request and its handling, so the
   window ended before `raise_for_status()` and before the enclosing `except`. There are **zero**
   unchecked consumers, and the raisers split roughly evenly between stopping and degrading.

The third error is the instructive one: it produced a **severity-above-the-flip emergency** —
"a 401 body becomes a supervisor result, live in OBSERVE today" — that does not exist. It was
about to be filed as its own board item. **A classifier that errs in three directions on one
corpus is a candidate generator, not an oracle.**

**Closing this item means READING each candidate, not re-running the script.** A flip gated on a
count from this classifier would be a signature over a guess — and the guess was wrong three
times in one evening.

## CONFIRMED MINTED — read individually

| site | credential | target |
|---|---|---|
| `dispatch_driver.py:221` | `mint_service_token()` → Bearer | cortex-bff `/internal/human_tasks/register` |
| `dispatch_driver.py:371` | `mint_service_token()` → Bearer | cortex-bff `/triage_tasks` |
| `extraction_review_sensor.py:555` | `Bearer {token}` | review start |
| `extraction_review_sensor.py:592` | `Bearer {token}` | review start |
| `dynamic_supervisor.py:1037` | `_telemetry_headers(config)` | engine-A `/analyze` |
| `dynamic_supervisor.py:1650` | `_telemetry_headers(config)` | engine leg |

**A question, not a finding:** `dispatch_driver` mints via `mint_service_token()`, which reads
`REVIEW_STARTER_CLIENT_ID` behind a general name — the exact shape that made the supervisor
dispatch as the review starter. It may be correct here (dispatch_driver runs in that process),
but *correct-by-coincidence and correct-by-design are different*, and the decoded subject on
those two calls should be witnessed rather than assumed.

## CONFIRMED — all 19 read individually 2026-08-10

No tooling. Each site read for target, credential mechanism, and 401 behaviour.
**All 19 are CONFIRMED-unminted** — not one attaches a credential by any mechanism.

### STOPS the caller — 11

| # | site | target | on 401 |
|---|---|---|---|
| 1 | `dispatch_driver.py:247` | engine-o `/write_item_state` | **TERMINAL** — `_fail_terminal_on_4xx` fires *before* `raise_for_status`, so a 401 is classed non-retryable and Restate will **not** retry it |
| 2 | `restate_analyst/main.py:544` | `ONTOLOGY_RESOLVE_URL` | raises, no local catch |
| 3 | `policy_rules_client.py:75` | engine-o `/policy_rules` | raises |
| 4 | `review_composer.py:94` | engine-o `/resolve_instance` | raises — every review fails to COMPOSE |
| 5 | `spo_interview.py:113` | engine-o `/classes` | raises |
| 6 | `spo_interview.py:154` | engine-o `/operable_subjects` | raises |
| 7 | `spo_interview.py:176` | engine-o `/find_compatible_verbs` | raises |
| 8 | `spo_step_executor.py:96` | engine-o `/find_compatible_verbs` | raises |
| 9 | `agent_routers.py:65` | engine-A `/analyze` | raises |
| 10 | `agent_routers.py:193` | DA `/analyze_data` | raises |
| 11 | `dynamic_supervisor.py:146` | engine-o `/plan` | raises — **in the `else:` branch, outside the `try` that guards the `if`** |

### DEGRADES — 8

| site | target | on 401 |
|---|---|---|
| `restate_analyst/main.py:2157` | engine-o `/classes` | `try` + explicit `status_code == 200` |
| `decision_record_writer.py:71` | engine-o `/write_decision_record` | handled — logs *"the corpus has a HOLE here"* |
| `dynamic_supervisor.py:280` | engine-o `/resolve` | raises inside `try`/`except` |
| `dynamic_supervisor.py:362` | engine-o `/find_compatible_verbs` | raises inside `try`/`except` |
| `dynamic_supervisor.py:679` | engine-o `/classify_predicate` | raises inside `try`/`except` |
| `gateway.py:124` | engine-o `/mesh/config` | `try`/`except` |
| `gateway.py:956` | engine-o `/instances_by_property` | `try`/`except` → 502 to the client |
| `gateway.py:2641` | engine-o `/route_intent` | `try`/`except` |

### Reading disagreed with the script AGAIN — same direction both times

The script said **9 stop / 10 degrade**. Reading says **11 / 8**. Two corrections, both
under-counting the stops:

* **`dynamic_supervisor.py:146`** — the script saw a nearby `try` and called it caught. That
  `try` guards the **`if config.task_plan_json:`** branch; this call is in the **`else:`**. A
  backward scan for `try:` cannot see which branch it belongs to.
* **`spo_interview.py:176`** — same false catch, from an unrelated enclosing block.

**A fourth distinct failure mode for the classifier: proximity is not enclosure.** Every one of
its four errors has been *structural* — indirection, over-resolution, window length, scope — and
none was a typo. That is what "read the candidates" was for.

### Two severities the counts hide

* **`dispatch_driver.py:247` is worse than "stops".** `_fail_terminal_on_4xx` classifies 4xx as
  terminal, so under REQUIRE the disposition write fails **permanently** rather than retrying —
  the durable-execution equivalent of a hard fail. Also note `/write_item_state` is one of the
  **12 undeclared routes**: unminted caller *and* unclassified gate.
* **`decision_record_writer.py:71` degrades into a provenance gap.** Its own log says *"the
  corpus has a HOLE here"*. Under REQUIRE that hole becomes routine rather than exceptional —
  decisions execute and go unrecorded, which is quieter than a stop and worse for audit.

### The numerator

**19 of 19 unminted; 11 must be remediated before REQUIRE, 8 would degrade.** Every one targets
engine-o, engine-A or DA — no third-party calls in this set. `transport-flip` has a real
numerator for the first time.


## THE IDENTITY RULING — settled 2026-08-10, the remediation's first line

**Default: each caller mints as its PROCESS identity.** `svc:engine-a` for the eight
`restate_analyst` sites, `svc:supervisor` for the three Dagster sites.

**The test that settles it** is the one that decided `svc:review-starter` vs `svc:engine-a` in
the identity-granularity ruling: *would the credential change the answer to any `can_invoke` /
`can_act` question, now or in a planned grant?* For the eight engine-o calls — resolution,
planning, predicate search — the answer is **no**. They are reads and internal orchestration,
ungoverned, so they carry the process's credential and any per-module attribution rides in the
payload rather than in the identity.

### `dispatch_driver:247` is ruled SEPARATELY, and keeps the review-starter identity

It writes **disposition state** — the review-starter's own governed downstream effect — and
`svc:review-starter` holds the capability the ceremony granted. So this call carrying
`svc:review-starter` is **correct by design**, not merely by the hardcoding's coincidence.

**But the coincidence is retired anyway.** `mint_service_token()` is a general name over specific
behaviour (it reads `REVIEW_STARTER_CLIENT_ID`) — the exact shape that made the supervisor
dispatch as the review starter. It becomes a call to the parameterised
`mint_token(client_id=..., secret_env=...)` with the `REVIEW_STARTER_*` values supplied **at the
call site**, so the identity is *chosen there and visible in the diff* rather than inherited from
a helper's body.

Correct-by-design and correct-by-coincidence can look identical in a green system; the difference
only shows when someone reuses the helper.

### Which gives the seam its shape

**The new helper takes the identity as an ARGUMENT, never resolves it from the module** — same
rule as `engine_mint`, same reason. Eight callers pass `svc:engine-a`, dispatch passes
review-starter, and the choice is legible at each site instead of embedded in a name.

### Acceptance

**Decode-witness the first token from each identity on the new seam — two decodes.** They are
what distinguish *"the helper works"* from *"the helper mints who we think it does"*, and that
distinction is the one this project has paid for twice.

## SEAM READ — the 11 are 2 identities across 2 processes, not 11 edits

**Done 2026-08-10, before scoping remediation, because "eleven edits" and "two seams" are very
different sessions.**

Every stopping caller sits in one of two processes, and the identity each should mint as follows
from the process, not from the call:

### Process A — engine-A's image (`agent_fleet/restate_analyst/*`) → `svc:engine-a`

8 of the 11: `dispatch_driver.py:247` · `main.py:544` · `policy_rules_client.py:75` ·
`review_composer.py:94` · `spo_interview.py:113,154,176` · `spo_step_executor.py:96`

**A mint already exists in this process.** `main.py` carries `engine_mint(...)` (registration,
`svc:engine-a`) and `dispatch_driver.py` carries `mint_service_token()`. What is missing is a
shared outbound-header helper, not a credential.

### Process B — the Dagster plane (`src/iagent/defs/*`) → `svc:supervisor`

3 of the 11: `dynamic_supervisor.py:146` · `agent_routers.py:65,193`

**The seam already exists and is already used**: `_telemetry_headers(config)` mints
`svc:supervisor` and is applied at `dynamic_supervisor.py:1037` and `:1650`. Site `146` is in the
same file and does not use it.

### What this means for scoping

| | count |
|---|---|
| call sites | 11 |
| modules | 6 |
| **processes / identities** | **2** |
| **seams needing new code** | **1** (an engine-A outbound-header helper) |

Process B needs no new mechanism — three calls need to pass the helper their own module already
defines. Process A needs one helper, then eight call sites pass it.

**Caveat, stated because it is the load-bearing assumption:** this says each caller *should* mint
as its process identity. That is the per-engine ruling applied to outbound calls, and it is the
right default — but `dispatch_driver` already mints via `mint_service_token()`, which reads
`REVIEW_STARTER_CLIENT_ID` behind a general name. Whether engine-A's outbound calls should carry
`svc:engine-a` or `svc:review-starter` **depends on which is the governed actor for each call**,
and that is a ruling, not a read. It should be settled once, at the helper, rather than eleven
times at the call sites.

## Not swept — what remains

~~`iagent-mesh-sdk`~~ swept (repo 2) · ~~`dag-tools`~~ swept (repo 3) · ~~`doc-tools`~~ swept (repo 4).

**Still unswept:** `cortex-ui` (browser calls terminating on gated routes). **Stated because "the repo I was in" is exactly how `review_composer` stayed
invisible** while the platform's registration callers were being enumerated carefully.

`cortex-ui` is the one where this method does not transfer unexamined — a JS/TS corpus whose
call-site idioms differ from every Python pass above. Budget it as a method problem first and a
reading problem second.


## THE FOUR-REPO SWEEP NOW ANSWERS TWO QUESTIONS

Ruled 2026-08-10: `/workflow/start` is to be **disabled, gated on a cross-repo consumer sweep**.
Its `consumers: [none-found]` is a static-analysis result over the repos swept so far, and
`dag-tools` / `cortex-ui` are plausible callers of a workflow-start endpoint.

> ### ANSWERED AND ACTED ON — 2026-08-11
>
> **5 of 5 repos, zero consumers.** `cortex-ui` — the one that mattered in the original
> conjecture — turned out to be a **structural** zero rather than an empirical one: a static SPA
> behind nginx with no server-side origin, so it cannot be a consumer of anything server-side.
> That is a stronger negative than "we looked and found none."
>
> `/workflow/start` is now **retired behind a 410**, `ENABLE_WORKFLOW_START` reverses it. See the
> EXECUTED section in `endpoint-gating-undeclared-routes-recommendation.md`.
>
> **This packet's second question is CLOSED.** The unminted-caller question continues below. The
> status paragraph that follows is kept as the record of how the sweep read mid-flight.

**Status (as of repo 4): 3 of the 4 answered — all NO.** `iagent-mesh-sdk` (repo 2) and `dag-tools` (repo 3)
have **no `/workflow/start` consumer**; the dag-tools check covered all file types, not just
`.py`, so a config- or template-driven caller would have shown. `doc-tools` (repo 4) also has
**no `/workflow/start` consumer** — established by endpoint enumeration, not call-site grep (see
repo 4 below). Only `cortex-ui` remains, and **it is the one that mattered in the original
conjecture** — a browser
calling a workflow-start endpoint is the plausible consumer. The disable decision is not
unblocked by these two NOs.

**That is the same read this item already owes.** While sweeping the four unswept repos for
unminted outbound callers, also record **any caller of engine-a's `/workflow/start`**. Same
files, same pass, two answers:

1. unminted callers → this packet's remaining rows;
2. `/workflow/start` consumers → the disable decision in
   `endpoint-gating-undeclared-routes-recommendation.md`.

**Verify-then-disable, never disable-and-discover** — a disabled route with a live consumer is
the silent-refusal class, which is what this arc has spent a week removing.


## REPO 2 of 5 — `iagent-mesh-sdk`, all 4 sites READ 2026-08-10

Grep to locate, reading to classify. **`/workflow/start`: no consumer in this repo** (grep over
all `.py`, zero hits).

| site | credential | mechanism | on 401 |
|---|---|---|---|
| `client.py:48` | **CONFIRMED-MINTED** | `_authorization()` → `mint_mesh_token()`; `MESH_DEV_TOKEN` only as an announcing dev fallback | `raise_for_status()` → **STOPS** |
| `core.py:342` | **CONFIRMED-UNMINTED** | none — bare `client.post(...)`, no `headers=` at all | `raise RuntimeError` on non-200 → **STOPS** |
| `registration_transport.py:114` | **MINTED IF the caller passes `mint`** | `headers` built from the `mint()` argument | caught → `RegistrationResult` → **DEGRADES** |
| `service_identity.py:62` | **N/A** | targets **Keycloak's token endpoint**, not a mesh service — `transport_auth` never sees it | — |

### THE FINDING — the SDK ships TWO registration paths and `MeshTool` uses the unminted one

`registration_transport.py` was added in v0.3.0 precisely to be the **one authenticated
registration transport**, with the mint, the ADR-0006 retry semantics and a named failure. The
platform now binds it.

**The SDK's own consumer was never converted.** `core.py:244` — inside `MeshTool`'s lifespan —
still calls `core.py:298 _emit_to_registrar`, which is a bare POST with no credential, no retry,
and `raise RuntimeError` on any non-200.

So **any externally-scaffolded engine using `MeshTool` registers unminted and STOPS under
REQUIRE** — the same defect as `review_composer`, in the package that exists to prevent it.

**This is my own two-transcription hazard, unfixed at the source.** The v0.3.0 commit message
argued that a second registration implementation is exactly what the one-implementation rule
forbids, moved the richer semantics into the SDK — and left the SDK's own path pointing at the
poorer one. Building the seam is not the same as wiring the consumers to it, and I reported the
former as though it were both.

**Not fixed here** (enumeration only). It is a one-line rebind — `_emit_to_registrar` calls
`register_with_mesh(...)` with a `mint` — and it belongs in the remediation window with the
platform's eleven.

### Running total

| repo | sites | unminted | stops | degrades |
|---|---|---|---:|---:|
| invincible-agent | 19 | 19 | 11 | 8 |
| iagent-mesh-sdk | 4 (3 in scope) | **1** | **2** | 1 |
| dag-tools | — | not swept | | |
| doc-tools | — | not swept | | |
| cortex-ui | — | not swept | | |

`client.py:48` stops on 401 but is **minted**, so it stops only if its credential is *rejected* —
a different failure from having none.

## REPO 3 of 5 — `dag-tools`, swept 2026-08-10

30 grep hits → **15 distinct call sites**, each read. `/workflow/start`: **no consumer**
(zero hits across all file types, not just `.py`).

The `/workflow/start` negative was run **twice, with different exclusion semantics** — once with
ripgrep, which honours `.gitignore` and therefore skips `dist/`, `tmp/` and the stray
`.tmp_dagster_home_*` trees, and once with a plain recursive `grep` that walked them. Both
returned nothing. Stated because `verify-then-disable` puts weight on this negative, and a
gitignore-respecting search alone would not have looked inside a built artifact.

### The headline is a NEGATIVE, and it is the useful kind

**`dag-tools` contributes ZERO stopping callers to `transport-flip`.** Not "none found" — the
negative is structural and holds on two independent axes:

1. **No mesh SDK anywhere.** `transport_auth`, `mint_mesh_token`, `register_with_mesh`,
   `MeshTool`, `MeshClient`, `iagent-mesh` — zero hits in `dag_tools/` and zero in
   `pyproject.toml`. dag-tools has no minting mechanism because it has no mesh dependency.
2. **No platform target.** The complete list of env-configured endpoints is
   `BROKER_URL` · `CENTRAL_GATEWAY_URL` · `CORTEX_BROKER_URL` · `RESTATE_*` (dag-tools' own),
   `REDIS_URL` · `KEYCLOAK_TOKEN_URL` · `TOPAZ_URL` · `DATAHUB_SERVER` · `AWS_*` (infra),
   `API_BASE_URL` · `ORACLE_*` · `SQLSERVER_DSN` (external). **Not one invincible-agent
   service.** A name grep for engine-o / engine-a / DA / cortex-bff routes returns nothing.

Axis 2 is what makes this trustworthy. Axis 1 alone would be the same weak negative that let
`review_composer` hide — "I looked and didn't see it". Enumerating every configured endpoint and
finding the platform absent from the *whole list* is a different claim.

### The 15 sites

| # | site | target | credential | on 401 |
|---|---|---|---|---|
| 1 | `cortex_data/client.py:83` | gateway `/assets/{urn}/authorize` | **MINTED** — Bearer, M2M or `MESH_DEV_TOKEN` | `raise_for_status` → **STOPS** |
| 2 | `central_gateway/main.py:307` | broker `/api/v1/internal/resolve` | **UNMINTED** — bare post, no `headers=` | explicit status check → 502 → DEGRADES |
| 3 | `domain_broker/main.py:247` | gateway `/api/v1/internal/register` | **UNMINTED** — bare post, no `headers=` | raises, caught at both callers → DEGRADES |
| 4 | `restate_dlt_sync/component.py:154` | dag-tools Restate ingress | **UNMINTED** | `except` → `log.warning` → **DEGRADES SILENTLY** |
| 5 | `restate_api_sync/component.py:159` | dag-tools Restate ingress | **UNMINTED** | `except` → `log.warning` → **DEGRADES SILENTLY** |
| 6 | `restate_handlers/serve.py:92` | Restate **admin** `/deployments` | **UNMINTED** | retry loop, never raises → DEGRADES |
| 7 | `cortex_data/client.py:53` | **Keycloak** token endpoint | n/a | — |
| 8 | `central_gateway/main.py:177` | **Topaz** `/api/v2/authz/is` | forwards the caller's token | non-200 → hard DENY (ADR-0026) |
| 9-12 | `resources/grist.py:71,86,100,103` | **Grist** (external) | Grist API token | — |
| 13 | `restate_handlers/api_sync.py:38` | external REST (`API_BASE_URL`) | `API_KEY` if set | — |
| 14 | `sap_induction/sap_client.py:46,70,72` + `service.py:77` | **SAP** OData + callback webhook (external) | own refresh | — |
| 15 | `qual/*` (7 hits) | **Dagster GraphQL** webserver | optional Bearer | — |

`io_managers/cortex_io_manager.py:153` is not a site — it delegates to `CortexDataClient` and
inherits row 1's minted posture. `s3_sensor/arrow_component.py:51` is not HTTP.

**Sites 2-6 are unminted but NOT flip blockers**, because their targets are not
transport-auth-gated — they are dag-tools' own services and its own Restate. They are recorded
because "unminted" and "ungated" are the same fact seen from the two ends, and the next section
is what that fact looks like from the receiving end.

### WHAT THE SWEEP ACTUALLY FOUND — a second mesh with two unauthenticated internal routes

Reading the *targets* rather than only the callers turned up the finding of this pass.

| route | auth dependency |
|---|---|
| `central_gateway` `/api/v1/assets/{urn:path}/authorize` | `Depends(security)` — HTTPBearer + Topaz |
| `central_gateway` `/api/v1/internal/register` | **NONE** |
| `domain_broker` `/api/v1/internal/resolve` | **NONE** |

`/api/v1/internal/register` takes `broker_url` and `asset_urns` **from the request body** and does
`SETEX mesh_route:{urn} 300 {broker_url}` for each. **Any in-cluster caller can repoint the
routing table for any URN at any URL.** The gateway then POSTs the resolve to that URL and returns
whatever ticket comes back — `physical_uri` and `credentials` included — to the user.

Topaz still gates the URN, so this does not hand an attacker data they lack entitlement to. What
it hands them is **integrity and availability**: serve an entitled user a poisoned ticket, or
overwrite every route with a dead URL.

**This is the `approval-bypass-bpmn-runner` shape exactly** — an unauthenticated write to a
control plane, mitigated only by in-cluster reachability. `centralGateway.ingress.enabled`
defaults to `false`, so the mitigation holds today; the chart ships a working Ingress template, so
it is one values flip from public. The BOARD's phrasing for the platform instance applies verbatim
here: *that mitigation does not travel to the work cluster.*

### Two severities the "DEGRADES" column hides

* **Site 3 degrades into a total data-plane outage that reports as 404.** The broker's own comment
  at `main.py:259-263` states it: the gateway holds `mesh_route:*` on a **300-second TTL** and the
  broker re-pushes every 120s precisely so one miss cannot empty it. A failure mode that blocks
  *every* push — not a hiccup — empties the routing table one TTL later, and the gateway then
  answers **404 "No active domain broker found"** for every asset. Loud in the broker's log,
  wrong-cause in the user's face. Retry-until-TTL is a hiccup mitigation; it is not a mitigation
  for a persistent refusal.
* **Sites 4 and 5 drop records while the asset materializes GREEN.** Both catch `Exception`, log
  at `warning`, and continue the loop. A blanket refusal drops every chunk / every record and the
  Dagster asset still reports success. That is the `[[silence-closure-arc]]` class — not an error
  presenting as silence, but a *failure presenting as success*.

### One inversion worth naming

`CortexDataClient.__init__` sets `self.jwt_token = jwt_token or os.getenv("MESH_DEV_TOKEN")` and
only falls through to `_fetch_m2m_token()` **if that is empty**. So `MESH_DEV_TOKEN` takes
**precedence over** real M2M credentials — an environment carrying both silently authenticates
with the dev token.

The SDK's `client.py:48` orders these the other way, with `MESH_DEV_TOKEN` as an *announcing* dev
fallback. Same two credentials, opposite precedence, no announcement on this side. Not a flip
blocker; a live footgun for work-deploy, where a leftover `MESH_DEV_TOKEN` would mask the M2M path
being misconfigured — and it would mask it *green*.

### Running total

| repo | sites | unminted | stops | degrades | flip blockers |
|---|---|---|---:|---:|---:|
| invincible-agent | 19 | 19 | 11 | 8 | **11** |
| iagent-mesh-sdk | 4 (3 in scope) | 1 | 2 | 1 | **1** |
| dag-tools | 15 | 5 | 1 | 5 | **0** |
| doc-tools | — | not swept | | | |
| cortex-ui | — | not swept | | | |

dag-tools' one STOP (site 1) is **minted**, so it stops only if its credential is *rejected* — the
same distinction recorded for the SDK's `client.py:48`.

### Disposition — this pass produced a finding that has no home yet

The register-route finding is **not** a `transport-flip` blocker and does not belong in this
packet's remediation window. It is a cross-repo instance of the exact question
`undeclared-routes` is blocked on — *is in-cluster reachability an acceptable gate?* — and it
strengthens that item's case by showing the pattern is not confined to the platform.

**Ruling needed, not a read:** fold it into `undeclared-routes` as a cross-repo instance, or file
it as its own board item alongside `approval-bypass-bpmn-runner`. Recorded here so the choice is
made deliberately rather than by the finding quietly aging out.

## REPO 4 of 5 — `doc-tools`, swept 2026-08-11

**One CONFIRMED unminted caller. Zero `/workflow/start` consumers.**

> ### REMEDIATED 2026-08-12 — and it needed a NINTH identity first
>
> `semantic_linker.py` now mints as **`svc:doc-tools`**. That identity did not exist: the eight
> were supervisor, data-analyst, review-starter and engines a/d/e/o/w, and doc-tools is none of
> them. Reusing one would have been the `mint_service_token()` defect **committed on purpose**.
>
> **The identity stanza was ITEM ZERO, not a follow-up** — a call cannot mint as a subject that
> does not exist. `policy/users.yaml` (instance nine, `groups: []`) plus the `iagent-doc-tools`
> client in the platform's `serviceClients`. The governance test decided the grants: its one call
> is a READ that changes no routing and no governed state, so per-process identity with **zero**
> capability grants is the correct default.
>
> **First identity for a workload this chart does not deploy.** doc-tools is a separate helm
> release, so the client is created by the platform's realm import and the secret is consumed by
> doc-tools' own chart. **Two charts, one credential, and nothing fails loudly if they drift** —
> under OBSERVE a failed mint just logs and the call proceeds. The decode-witness is what closes
> that gap; until then, matching `docToolsClientSecret` to `DOC_TOOLS_CLIENT_SECRET` is a manual
> invariant.
>
> **A SECOND DEFECT AT THE SAME LINE, and it is the one the guard predicted.**
> `ONTOLOGY_SVC_URL` defaulted to `http://ontology-agent-svc.default.svc.cluster.local:8084` — the
> forbidden legacy-DNS pattern, as a **live default**, and the env var was never set in
> doc-tools' chart. So this call had been pointing at a host that does not resolve in the current
> cluster. `[[legacy-dns-guard-phantom-scope]]` said the guard "passes green while the forbidden
> pattern is live in the unscanned tree." **It was, it was exactly one line, and it was this one.**
> A disproved guard is worse than a missing one; here is the proof, with a name and a line number.
>
> The seam lives in `doc_tools/utils/mesh_identity.py` rather than in the asset, because
> `doc_tools/__init__.py` eagerly imports the whole definitions graph — so a helper defined in the
> asset could only be exercised where dagster + dagster_aws + datahub all install, and its pins
> would have SKIPPED everywhere else. 8 pins, and the behavioural ones RUN.

> ### THE COUNT WAS 2 AND IS 1 — corrected 2026-08-12
>
> `transport-flip`'s `blocked-on` read *"2 CONFIRMED unminted callers (dag-tools, doc-tools →
> engine-o)"*. **dag-tools contributes ZERO.** The flip's numerator is **1**: this row.
>
> Three independent reads agree, and the first two were already written down:
>
> | evidence | says |
> |---|---|
> | this packet's own running total (repo 3) | `dag-tools: 15 sites, 5 unminted, **0 flip blockers**` |
> | this section's own heading | **One** confirmed unminted caller |
> | fresh read of `dag_tools/**.py`, 2026-08-12 | **zero** references to engine-o, ontology-svc, or any platform route |
>
> The only grep hits in dag-tools are `qual/registry/client.py` using `classes/` as an **S3 path
> segment** — the word, not the route. dag-tools' five unminted calls target *its own* services
> and *its own* Restate ingress, none of which transport auth gates; that is why the table says 0.
>
> **How the duplicate formed:** the line was written while doc-tools was still unswept, and
> "dag-tools" attached to findings that ARE dag-tools work — the unverified-subject gateway and
> the unauthenticated broker register — but are **not unminted callers to engine-o**. One item,
> two names, counted twice.
>
> **Why this was worth one read rather than an assumption:** an inflated precondition is the
> census-membership defect in the most expensive possible place. It makes the flip look further
> away than it is, and it would have sent someone hunting a dag-tools caller that does not exist —
> the mirror of `review_composer`, where the count was too *low*. The correction rests on the
> strong-form negative from the repo-3 sweep: **every configured endpoint in dag-tools was
> enumerated and no platform service appeared in the list**, which is a different claim from
> "I grepped and found none."

| # | site | target | verdict |
|---|---|---|---|
| 1 | `doc_tools/assets/semantic_linker.py:99` | engine-o `POST /classify_legacy_table` | **CONFIRMED unminted** |

```python
resp = requests.post(f"{ONTOLOGY_SVC_URL}/classify_legacy_table", json=dossier, timeout=30)
```

No headers. No `Authorization`.

### Four qualifying facts, each read — the standard this row is held to

1. **The route is real.** engine-o `agent_fleet/ontology_service/main.py:2094` serves
   `POST /classify_legacy_table`. Not a call into nothing.
2. **The caller is live.** `semantic_linker` is imported at `doc_tools/definitions.py:10` and
   included in `load_assets_from_modules(...)` at `:229`. Not dead code, not an example.
3. **Credentials were demonstrably available in the same file.** Lines 60 and 160 send
   `Authorization: Bearer {DATAHUB_TOKEN}` to DataHub GMS. **This is the fact that makes the row
   unambiguous: it is not a call that could not be minted, it is one that was not.**
4. **`raise_for_status()` on line 100.** Under REQUIRE it raises — the asset fails rather than
   degrading to an empty classification. Same shape as `review_composer`: it stops, it does not
   quietly resolve nothing.

`ONTOLOGY_SVC_URL` appears in exactly two places — its definition (`:8`) and this one call. One
caller, not a family.

### The negative was established by ENDPOINT ENUMERATION, not by grepping call sites

The axis-2 test from the `dag-tools` pass, and it is what makes the "one row" claim trustworthy
rather than a hope that enough greps were run. Enumerating **every configured endpoint** in
`doc-tools` — `DATAHUB_GMS_URL`, `JENA_URL`, `WEAVIATE_HTTP_HOST`/`_GRPC_HOST`, `S3_ENDPOINT_URL`,
`LLM_BASE_URL`, `OPENAI_BASE_URL`, `VISION_LLM_BASE_URL`, `SQLSERVER_HOST`, `ORACLE_HOST`,
`RABBITMQ_GIT_REPO_URL`, `DDS_GIT_REPO_URL` — shows that **exactly one is a platform service**:
`ONTOLOGY_SERVICE_URL`.

No `CORTEX_BFF_URL`. No `RESTATE_INGRESS_URL`. No `MESH_REGISTRAR_URL`. No engine-a endpoint of
any kind. That bounds the sweep from above: there is one platform-facing row because there is one
platform-facing endpoint, and the question "did I grep enough call sites?" does not arise.

A hardcoded-URL pass (`iagent-`, `engine-o`, `engine-a`, `cortex-bff`, `restate`, `mesh-registrar`,
`/workflow/start`, `/v1/register`) confirmed the same boundary from the other direction.

### A FALSE POSITIVE a call-site grep produces — in the alarming direction

`engine-a.mesh.svc:8081/execute` appears three times in `tests/test_aitool_linker.py`. It is **not a
call site**: it is an asserted **DataHub custom-property value** (`mesh_endpoint_url`) that doc-tools
*writes* to the catalogue. A grep for platform hostnames flags it as a caller of engine-a; reading it
shows doc-tools never calls that address at all.

**Fifth structural failure mode this sweep has avoided by reading rather than scripting**, and worth
recording so the classifier-was-wrong-three-times argument above stays evidence-backed: a string
naming a service can be data the repo *publishes* rather than an endpoint it *calls*.

### Filed separately — the guard that could not see this

The default on line 8 is `http://ontology-agent-svc.default.svc.cluster.local:8084` — the **legacy
DNS pattern** the platform's own guard forbids. That guard lists `"doc-tools"` in its scanned dirs
and has never scanned it. See `legacy-dns-guard-phantom-scope`; it is a disproved guard, not a
missing one, and it is filed at higher severity than this row.

## REMEDIATION BUILT — 2026-08-10, the 11 platform sites + the SDK rebind

**Safe to build unsupervised for one specific reason:** under OBSERVE, attaching a credential
where none was sent is behaviourally inert — receiving engines validate-if-present and refuse
nothing. The worst case is a mint failure, and the standing rule already covers it (log and
proceed in the expand phase, never raise).

### The seam

`agent_fleet/utils/service_identity.py` — `outbound_auth_headers(*, client_id, secret_env)`.
Identity is an ARGUMENT, same rule and same reason as `engine_mint`. Mirrors
`dynamic_supervisor._telemetry_headers` deliberately: same posture, same `X-Auth-Status`
diagnostic, same log-and-proceed.

**One property worth naming because it decided the test story:** `os.environ[secret_env]` is
evaluated BEFORE `mint_token` is entered, so an unconfigured environment raises `KeyError`
*locally* and never opens a socket. Unit tests that do not set the secret get a fast warning
rather than a real client-credentials POST against a nonexistent Keycloak — the exact hazard
`tests/test_dispatch_driver.py`'s fixture docstring warns about.

### The 11 sites

| process | identity | sites |
|---|---|---|
| engine-A image | `svc:engine-a` | `main.py` (ontology resolve) · `policy_rules_client.py` · `review_composer.py` · `spo_interview.py` ×3 · `spo_step_executor.py` — **7** |
| engine-A image | `svc:review-starter` | `dispatch_driver.py` `_write_disposition_state` — **1**, ruled separately |
| Dagster plane | `svc:supervisor` | `dynamic_supervisor.py` `create_task_plan` (via `_telemetry_headers`) · `agent_routers.py` ×2 — **3** |

**Two deviations from the packet's scoping, both deliberate:**

1. **`agent_routers.py` does NOT use `_telemetry_headers`.** That helper lives in
   `dynamic_supervisor` and takes a `config` these assets do not have. Reaching across for another
   module's private function is worse coupling than calling the shared helper with the identity
   named at the site — so both sites use `outbound_auth_headers` with `svc:supervisor`. Only
   `dynamic_supervisor.py` itself had the helper "its own module already defines".
2. **`agent_routers.py` imports the helper under a guard.** That module loads at Dagster
   **code-location** load time, so a hard `ImportError` takes the whole location down rather than
   failing one asset. The fallback restores exactly today's behaviour and *announces itself* — a
   silent one would be the defect being fixed.

`dispatch_driver` uses `os.getenv("REVIEW_STARTER_CLIENT_ID", "")`, not `os.environ[...]`: the
latter evaluates at the call site, **outside** the helper's guard, and would turn an unconfigured
env into a hard failure of a call that works today.

### The SDK rebind

`MeshTool.__init__` now takes `mint` (default `None`), and `_emit_to_registrar` calls
`register_with_mesh` instead of its own bare POST. `mint=None` reproduces today's unauthenticated
request exactly — but now with ADR-0006 retry and a named reason — so the rebind changes nothing
for engines that pass no identity. The `RuntimeError` on failure is **kept on purpose**:
`register_with_mesh` never raises, and the lifespan's "registration failure must not crash the
tool" handler depends on it.

**Guarded by `tests/test_registration_consumer_is_bound.py`** (5 pins), which encodes the law's
test — *who were the consumers, and which line binds each?* — rather than re-checking that a mint
happens. `[[consolidation-completes-at-the-last-consumer]]`.

**`v0.3.1` IS TAGGED AND PUSHED** (2026-08-11, annotated, `a934c61`) — so the release exists and
an externally-scaffolded engine can consume the fix today.

**THE PLATFORM STILL PINS `v0.3.0`, AND MOVING IT IS A DECISION, NOT A CHORE.** Three lines:
`pyproject.toml` ×2 and `agent_fleet/restate_analyst/pyproject.toml`.

> **The pin isn't there to be current. It's there to make the currency deliberate.**

`tests/test_sdk_pin_is_a_version.py` states the reason in its own words: the pin exists because
*"a single SDK commit would change every engine's security behaviour on the next rebuild — with
nobody deciding, and no diff in this repo to review."* **The bump IS that review.** An agent
performing it silently overnight would satisfy the letter of the test and defeat the whole of it —
producing exactly the undecided security change the pin was written to prevent, only with a green
suite attesting to it.

So "why hasn't this been bumped yet" has an answer that is not backlog: *because nobody has
reviewed it yet, and that is the mechanism working.* Three lines, when they are wanted — and **the
wanting is the point.**

The platform is not exposed meanwhile, and the reason is worth stating rather than assumed: its
engines register through `register_engine_to_mesh` → `engine_mint`, which already binds
`register_with_mesh`. The unbound consumer was `MeshTool`, which this repo does not use to
register. **The exposed party is the externally-scaffolded engine, not this repo** — which is
exactly why the defect stayed invisible from inside it.

### NOT done, and why

**`mint_service_token()` is NOT retired at `dispatch_driver:220`/`:373`.** Those two sites are
already correctly minted; retiring the misnamed helper there is a *legibility* refactor on working
code, and four test files — including `test_expired_token_seal.py`, a security seal — monkeypatch
that name in `dispatch_driver`'s namespace. Rewiring a seal's stub is a supervised change, not an
overnight one. The anti-propagation marker on the helper already stops new callers.

### Acceptance status

| check | state |
|---|---|
| affected suites (dispatch driver, expired-token seal, grouped review, promise name, identity separation, trace headers) | **54 passed** |
| SDK suite | **111 passed** + 5 new pins |
| **two decode-witnesses** (`svc:engine-a`, `svc:supervisor` on the new seam) | **OUTSTANDING — the morning read** |

The decode-witnesses are the acceptance. Everything above proves the helper *works*; only a
decoded subject proves it mints *who we think it does*, and that distinction is the one this
project has now paid for twice.

## REPO 5 of 5 — `cortex-ui`, read 2026-08-11 — **a STRUCTURAL zero**

Full design read in `cortex-ui-transport-idiom`. Summarised here so the enumeration's total is
readable in one place.

**Zero unminted callers, for a reason no amount of grepping would have produced:**

> **A static SPA cannot have an unminted server-side caller. There is no server.**

`package.json` has no server framework; the `Dockerfile`'s runtime stage is `nginx:1.25-alpine`
and copies only `/app/dist`, so **node is not in the runtime image**; `nginx.conf` has **no
`proxy_pass`**; the entrypoint writes a config file and execs nginx. Every call in this repo
originates in the **browser**, carrying the **human's** OIDC token — which is the design, not a
defect. The unminted-caller frame does not apply, **by category rather than by absence.**

**Axis-2 held, and bounded it to one endpoint:** `src/config.ts` declares five runtime keys, of
which exactly one is a platform service (`VITE_API_URL` → cortex-bff). Keycloak is the token
*issuer*, not a callee; `VITE_ELECTRIC_URL` is declared-but-dead. Eight transport sites total in
the whole application.

**What it DID surface is a different failure mode**, and is deliberately not counted in this
population: `NodeInspector.tsx:19` calls a gated bff route with **no Authorization header** — a
browser call that drops the user's token. Against a gated route that is a **broken panel**, not
an unauthenticated actor. It carries a second defect on line 6 (`import.meta.env` instead of
`config`, so the deployed image points at `localhost:8000`) and **the outer defect masks the
inner one** — fixing the config bypass alone would make the panel start rendering
`{"detail": "Not authenticated"}` as graph data.

**Sixth and seventh instances of the publish-vs-dial false positive**, and this repo is where the
mechanism is densest: `useCompileWorkflow.ts:54` emits `http://restate-agent-svc:8081/{id}` as an
`agent_endpoint` **field in a payload**, and `mockGroundingEmitter.ts` carries ~14 in-cluster URLs
inside **mock fixtures**. Ambiguous hostname strings outnumber real call sites roughly **two to
one** here. This remains the one mechanism a human reader would also plausibly get wrong at a
glance — the other four were tool artifacts; this one is a genuine ambiguity about what a
hostname in source *means*.

### The enumeration's total

| repo | confirmed unminted callers |
|---|---|
| platform (`invincible-agent`) | see rows above |
| `iagent-mesh-sdk` | see rows above |
| `dag-tools` | 1 |
| `doc-tools` | 1 |
| `cortex-ui` | **0 — structural** |

## Acceptance

- Every candidate above read and confirmed or reclassified.
- ~~Four remaining repos swept the same way.~~ **DONE 2026-08-11 — all five swept.**
- Each confirmed-unminted caller either minted, or exempted with a stated reason.
- A guard that fails when a new mesh-targeted outbound call appears unclassified — otherwise
  this is a one-time census and the next `review_composer` arrives unannounced.
  **cortex-ui: DONE 2026-08-11 (`2c3b8a9`)** — `scripts/check-transport-declarations.mjs`, wired
  into `npm run build` so an undeclared call fails the image build. Declare-your-exception shape;
  four scope/positive controls verified break-on-purpose; committed red-proof.
  **The platform side is still open**, and it is the one that matters more — the two CONFIRMED
  unminted callers live in `dag-tools` and `doc-tools`, and neither repo has an equivalent.

  Worth stating why the guard was worth building even though cortex-ui returned a zero: **the
  zero there is structural** (no server-side origin exists) and needs no guard, but the *browser*
  population is a searched zero and decays on the next component someone writes. A searched zero
  ships with a guard or it silently becomes false.
