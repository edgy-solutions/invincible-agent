# Unminted-caller enumeration — platform pass

> **STATUS: PLATFORM ONLY.** `iagent-mesh-sdk`, `dag-tools`, `doc-tools` and `cortex-ui` are
> **not swept** and are the majority of the remaining risk surface.

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

## Not swept — the majority of remaining risk

`iagent-mesh-sdk` (MeshClient.ask, registration transport), `dag-tools` (central_gateway,
CortexDataClient), `doc-tools` (ingest→mesh calls), `cortex-ui` (browser calls terminating on
gated routes). **Stated because "the repo I was in" is exactly how `review_composer` stayed
invisible** while the platform's registration callers were being enumerated carefully.


## THE FOUR-REPO SWEEP NOW ANSWERS TWO QUESTIONS

Ruled 2026-08-10: `/workflow/start` is to be **disabled, gated on a cross-repo consumer sweep**.
Its `consumers: [none-found]` is a static-analysis result over the repos swept so far, and
`dag-tools` / `cortex-ui` are plausible callers of a workflow-start endpoint.

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

## Acceptance

- Every candidate above read and confirmed or reclassified.
- Four remaining repos swept the same way.
- Each confirmed-unminted caller either minted, or exempted with a stated reason.
- A guard that fails when a new mesh-targeted outbound call appears unclassified — otherwise
  this is a one-time census and the next `review_composer` arrives unannounced.
