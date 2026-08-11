---
id:         unminted-caller-enumeration
status:     open
owner:      agent
blocked-on:
closed-by:
repo:       invincible-agent, iagent-mesh-sdk, dag-tools, doc-tools, cortex-ui
summary:    Static read of mesh-targeted outbound calls, classified minted/unminted with failure mode. Platform pass done; four repos outstanding.
---

# Unminted-caller enumeration — platform pass

**This is `transport-flip`'s real precondition.** The gauge is corroboration, not proof: it
measures traffic that occurred, not callers that exist.

> **STATUS: PLATFORM ONLY.** `invincible-agent` is swept below. **`iagent-mesh-sdk`,
> `dag-tools`, `doc-tools` and `cortex-ui` are NOT swept** and are the majority of the
> remaining risk surface. Do not read this as the answer.

## METHOD LIMITATION — read this before trusting any row

Two automated passes over the same tree **disagreed with each other**, and both were wrong:

* Pass 1 flagged `dynamic_supervisor.py:1037` UNMINTED. It is **minted** — the credential is
  attached inside `_telemetry_headers(config)`, so a literal search for `Authorization` in the
  call block finds nothing. **Indirection defeats a string match.**
* Pass 2 "fixed" that by resolving helpers and then reported only **1** minted call, dropping
  four that a read confirms are minted (`dispatch_driver.py:221,371`,
  `extraction_review_sensor.py:555`, `dynamic_supervisor.py:1650`) — the target-URL regex and
  the code window were too narrow.

So: **grep-and-classify is a candidate generator here, not an oracle.** Anything below marked
CONFIRMED was read; anything marked CANDIDATE was produced by a classifier that has demonstrably
erred in both directions on this exact corpus. Closing this item means reading each candidate,
not re-running a script.

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

## CANDIDATE UNMINTED — 19 sites, each needing a read

`RAISES` is the severity column. It is what turned the composer from a nuisance into a
pipeline-stopper: an unresolved subject is a handled outcome; a raised 401 is not.

| site | on 401 |
|---|---|
| `review_composer.py:94` | **RAISES** — verified; every review fails to COMPOSE |
| `dispatch_driver.py:247` | RAISES |
| `restate_analyst/main.py:544` | RAISES |
| `policy_rules_client.py:75` | RAISES |
| `spo_interview.py:113`, `:154`, `:176` | RAISES |
| `spo_step_executor.py:96` | RAISES |
| `agent_routers.py:65`, `:193` | RAISES |
| `dynamic_supervisor.py:146`, `:362` | RAISES |
| `gateway.py:124`, `:956`, `:2641` | RAISES |
| `restate_analyst/main.py:2157` | degrades |
| `decision_record_writer.py:71` | degrades |
| `dynamic_supervisor.py:280`, `:679` | unchecked — result used as-is |

**Fifteen of nineteen raise.** If these survive their reads, REQUIRE does not degrade the fleet —
it stops it, across the supervisor, the gateway, the SPO interview and the dispatch driver. That
is a materially different flip than "some callers get denied", and it is the single most
important output of this pass.

The three `unchecked` rows deserve their own attention: a 401 whose body is consumed as a result
is worse than one that raises, because it produces *wrong data silently* rather than stopping.

## Not swept — the majority of remaining risk

`iagent-mesh-sdk` (MeshClient.ask, registration transport), `dag-tools` (central_gateway,
CortexDataClient), `doc-tools` (ingest→mesh calls), `cortex-ui` (browser calls terminating on
gated routes). **Stated because "the repo I was in" is exactly how `review_composer` stayed
invisible** while the platform's registration callers were being enumerated carefully.

## Acceptance

- Every candidate above read and confirmed or reclassified.
- Four remaining repos swept the same way.
- Each confirmed-unminted caller either minted, or exempted with a stated reason.
- A guard that fails when a new mesh-targeted outbound call appears unclassified — otherwise
  this is a one-time census and the next `review_composer` arrives unannounced.
