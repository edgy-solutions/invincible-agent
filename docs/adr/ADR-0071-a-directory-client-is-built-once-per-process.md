# ADR-0071 — A directory client is built once per process

**Status:** Proposed, 2026-11-14. This records the design and a census; no code ships with it. Steps 1 and 2 are
built by `invincible-agent/lane/gov` in their own PRs, and this record cites them as they land.
**Date:** 2026-11-14
**Deciders:** architect (the 11-11 order and its 11-14 re-issue); Chris (11-14: step 3 becomes this ADR,
naming no outside framework).
**Owners:** the census and this record are `invincible-agent/lane/01` with `invincible-agent/lane/perf`. perf owns
the cost column. gov owns steps 1 and 2.
**Related:** the 11-12 entitlements stall: a BFF limited to half a core was throttled in 40% of its CPU periods, and
the UI gave up at 15 s.

---

## The problem

Every call to the permission directory builds a new HTTP client and discards it when the call returns.

- Building a client is not free. Most of the cost is the TLS context the client prepares by default, even when the
  directory's URL is plain `http://` and the context is never used.
- One `GET /me/entitlements` made about 37 directory calls, so it built about 37 clients:
  - 10 content-kind checks;
  - 1 capability listing;
  - 26 capability checks.
- **Measured once by Lane 1 on 2026-11-12:** about 70 ms of CPU per client, and about 2.6 s of CPU per GET.
  perf repeated the GET figure on 0.4.88: 2.224 s, 3 of 3 reps (the cost column below).
  - At the BFF's then-limit of half a core, the GET outlived the UI's 15 s timeout, and the server logged nothing for
    the abandoned request.
  - Raising the limit to two cores (0.4.86) hid the cost without removing it.

The pattern is not confined to that route. The census below finds it at 20 sites.

## Decision

1. **A process builds its directory client once and reuses it.**
   - It is built lazily on first use, guarded so that concurrent first calls build one client, and closed on shutdown.
   - A request never builds a directory client.
2. **The transport follows the URL.**
   - An `http://` directory URL gets a client with no TLS context.
   - An `https://` URL gets one TLS context, built once with the client.
   - The scheme is read from configuration, never assumed.
3. **Many questions about one caller are one call where the directory can answer them together.**
   - If it cannot, the record says so with the evidence, and the calls share the one client.
   - Any per-caller cache is short-lived and invalidated by a grant sync, so a grant change is seen on the next read
     after the sync.
4. **A batch job builds one client per run.** That is already the case (row 20) and is correct.
5. **The rule is held by a seal, not by review** (Check, below).

## Census (read at c4de4c29, 2026-11-14)

**How it was found.** The census searches for the form of the code, not for names:
- an HTTP client constructed inside a function body;
- or a module-level request call, which builds a client per call;
- whose target is the permission directory's URL setting.

**How each site is classed:**
- **answer:** reached when a user asks a question;
- **request:** reached by another request route;
- **batch:** a job run.

"Dark" means the call is behind the agentic-authorization flag. That flag is `false` in the chart's defaults, and no
values file sets it. A dark site makes no directory call today, but it does the moment the flag turns on.

| # | site | function | class | note |
| --- | --- | --- | --- | --- |
| 1 | `agent_fleet/ontology_service/main.py` | `_can_view_class` | **answer, dark** | `/resolve`: one call per candidate class, no dedupe; the supervisor calls `/resolve` on every answer |
| 2 | the metadata-catalogue wrapper engine | its view check on `query_metadata` | **answer, dark** | reached through the analyst engine's `/analyze`, which the supervisor calls |
| 3 | `src/iagent/human_tasks.py` | `_resolve_audience_actors` | request | task registration and triage |
| 4 | same | `can_act_or_unavailable` | request | `POST /human_tasks/{id}/act` |
| 5 | same | `can_invoke_or_unavailable` | request | `/me/entitlements`; the ingest content-kind gate |
| 6 | same | `check_can_invoke` | request | triage |
| 7 | same | `capability_object_exists` | request | `/me/entitlements`; the content-kind gate |
| 8 | same | `capability_keys` | request | `/me/entitlements` (paged) |
| 9 | `agent_fleet/ontology_service/main.py` | `_can_invoke_capability` | request | item-state and decision-record writes |
| 10 | the vector-store engine (engine-w) | `_can_read_document` | request, dark | one call per hit, on its own query route; the supervisor does not call it |
| 11 | the graph-store engine | `_can_read_document` | request, dark | reached from an orchestrator asset, not from an answer |
| 12 | `agent_fleet/docs_agent/entitlement.py` | `can_invoke` | request | the docs engine's partition step |
| 13 | the analyst engine's review starter | `can_invoke_start_review` | request | starting a review |
| 14 | the analyst engine's step executor | `check_can_invoke` | request | running a definition |
| 15 | same | `check_can_act` | request | authorizing a resolution |
| 16 | `agent_fleet/utils/entitled_domains.py` | `entitled_domains` | request | engine-fin's artifact route |
| 17 | `agent_fleet/utils/export_capability.py` | `can_export` | request | engine-cost and engine-fin exports |
| 18 | `agent_fleet/utils/program_membership.py` | `can_view_program` | request | the ontology service's instance resolve, engine-fin, engine-safety and the BFF |
| 19 | `agent_fleet/utils/recipient_readers.py` | `can_read_recipient` | request | engine-cost, engine-fin and the BFF |
| 20 | the policy sync client | its constructor | batch | one client per run: **conforms** |

**Already conforming:** the BFF's entitlement client in `src/iagent/authz/` is built once, lazily and behind a lock
(`src/iagent/auth.py`). Every authenticated request, including the answer route, uses that one client, and it caches
per token.

**What the answer path pays today.** It pays only the conforming client (once per token, then cached). Rows 1 and 2
cost nothing while the flag is off. When the flag turns on, **row 1 is the first cost**, because it makes one call
per candidate class on every answer. So it is fixed before the flag moves, not after.

**Undecided: none.** The first pass left five rows undecided (1, 2, 10, 11, 12). Each was traced to its caller
before this record was written.

## Cost column (perf)

| measure | before | after step 1 | after step 2 |
| --- | --- | --- | --- |
| CPU per `/me/entitlements` (BFF) | **2.224 s** (perf, 0.4.88: 3 of 3 reps, range 2.191–2.272). Lane 1's earlier ≈2.6 s was n=1 (11-12). | owed: perf, on the sandbox roll that carries #402 and #403 | owed: perf, same roll |
| clients built per `/me/entitlements` | ≈37 | 0 after warm-up (the seal) | 0 |
| directory calls per `/me/entitlements` | ≈37 | ≈37 | 2, by gov's seal (#403); unmeasured on sandbox |
| CPU per answer, flag on (row 1) | owed: perf; it cannot be measured while the flag is off | — | — |

gov's dev-box figures for step 1 (37 calls at 18.8–21.9 ms of CPU each) are not comparable to sandbox. They show the
direction, not the after-figure.

**Method (the accepted one, perf's):**
- cAdvisor `container_cpu_usage_seconds_total`, read through the apiserver's node proxy, with no exec into the pod.
- The s2-freshness rule, and the idle subtraction.
- 5 GETs per rep, three or more reps.
- The command is `ent_cpu.py`. Record it, not just the figure.
- The before-figure is perf's measurement of 2026-11-14 on 0.4.88.

## What iagent builds from it

- **Step 1 (gov):** rows 3–8 use one client per process, with the transport following the URL. This is the 0.4.89
  train.
- **Step 2 (gov):** one batched capability call where the directory supports it, and a short per-user cache
  invalidated on a grant sync. Each change is measured separately.
- **The shared helpers, rows 16–19:** one module change gives every engine that imports them a process-wide client.
  This is the next PR after step 1.
- **Row 1, before the flag moves:** one client, plus one batched check across the candidate set, or a dedupe.
- **Rows 2 and 9–15:** one client per process each.

## Check

The seal is owed by step 1's PR and extended by each later row. It is not built here.

- **The test.** For every module that reads the directory's URL setting, it fails on an HTTP client constructed
  inside a function body.
- **The exemption list.** It names each conforming construction by this ADR's row number. An entry with no row fails.
  So does a row whose site no longer exists.
- **The positive control.** Re-introduce a per-call client in row 3's function, and the seal must go red. Restore
  it, and the seal must go green.
- **The runtime half.** Count client constructions across one `/me/entitlements` request after warm-up. The count
  must be 0.

## What this does not establish

- That the directory supports a batched check. Step 2 finds out and records the evidence.
- A cost for rows 2 and 9–19. Only the entitlements route has been measured.
- Anything about non-directory clients (model gateway, stores, the workflow runtime). They may share the pattern,
  but they are outside this record.
