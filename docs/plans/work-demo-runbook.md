# Work-cluster demo runbook — PCN/PDN sustainment, end-to-end on the AUTO pipeline

Orchestrates the sustainment demo on the work cluster. Written against the pipeline we
actually want: a dropped notice **flows to a review by itself** — the extraction→review
Dagster sensor (`iagent.defs.extraction_review_sensor`) is the canonical trigger, not a
human with `curl`. Beat 2 is **"watch it arrive"**, not "POST it". The manual `POST /reviews`
is kept only as the deterministic fallback (ops / re-drive path).

> Run WITH a human on the work cluster (it is off-limits to autonomous action). Work identity
> is **employee-id**, not email — every subject below is stated SYMBOLICALLY (reviewer /
> dispatch-actor / auto-starter); bind them to real employee-ids in `task_grants.yaml` at run
> time. Deployment names resolve by EXACT match, never a grep — confirm them in `kubectl get deploy`
> before you start.

---

## A. Substrate: prime, THEN load, THEN verify (they are different steps)

`prime-substrate-job` **provisions + uploads** — it is not the load:
- Neo4j constraints, Fuseki dataset provisioning, and it **uploads the canonical TTLs to MinIO**.
- It survives deploys (setup, not runtime).

The **canonical ontology pipeline** does the actual **load**:
- the ontology-ingest Dagster sensor + `ingest_ontology_job` + `sync_jena_ontologies_to_neo4j`
  load the TTLs into **Fuseki + Neo4j + Weaviate**.
- engine-o additionally loads the IOF/MRO ontology into in-memory rdflib **at startup** (so an
  engine-o that started before the load has a stale in-memory view — roll it AFTER the load).

**Order:** `prime-substrate-job` → wait for the ontology-ingest to complete → **roll engine-o** →
then verify (§C). Do NOT assume "prime ran" means "the graph is queryable".

---

## B. Grants — deny-by-default, git-rails only (never hand-surgery Topaz)

Three DISTINCT things are in play here, and they are commonly conflated. Only **one** of them
is toggled by `ENABLE_DISPOSITION_AUTHZ` — read this table before you decide what to skip:

| what | how | gated by `ENABLE_DISPOSITION_AUTHZ`? |
|---|---|---|
| **1. auto-starter identity + token** (the sensor authenticates to `/reviews`) | Keycloak client-credentials client `iagent-review-starter` (or the static-token shim), **not** a grant | **no** — `/reviews` is `Depends(get_current_user)`; a valid token is ALWAYS required |
| **2. auto-starter `can_invoke(mesh:startReview)` capability** | `policy/capability_grants.yaml` → `svc:review-starter` | **YES — this is the only thing the env gates** |
| **3. reviewer / dispatch-actor audience grants** (WHO the tasks route to) | `policy/task_grants.yaml` audiences `pcn_disposition:SUSTAINMENT` + `qualification` | **no** — deny-by-default *routing*, not a togglable check |

All grants go through `task_grant_sync` / `capability_sync` (validate → reconcile → readback →
prune); never hand-surgery Topaz.

> ### FLIP RIDER — sandbox is now `ENABLE_DISPOSITION_AUTHZ=true` (2026-07-31)
> Sandbox **no longer runs the gate-off config described below.** It was flipped ON during the
> refusal-routing witness, because the two sibling gates had drifted into different states and
> that asymmetry is the dangerous one: `mesh:fileTriageTask` is enforced in cortex-bff with **no
> toggle** (always live, fail-closed), while `mesh:startReview` sat behind this unset env and
> **no-op-returned True**. One live gate + one dark gate reads as "the gates are on" — and it had
> already corrupted a claim: the svc:review-starter witness passed **without its capability gate
> ever being exercised**.
>
> **Both gates are now live in sandbox and both grants are synced** (`capability_grant_sync`,
> readback `checked=3 failures=0`), witnessed deny-before-grant, then allow.
>
> **What work's equivalent state must be at deploy — decide it EXPLICITLY, do not inherit it.**
> If work runs `ENABLE_DISPOSITION_AUTHZ=true`, `capability_grants.yaml` must carry BOTH
> `mesh:startReview` **and** `mesh:fileTriageTask` for the service identity, or notices refuse
> loudly at start and refusals fail to route. If work leaves it unset, note that
> `mesh:fileTriageTask` is enforced **regardless** — the triage gate has no toggle — so that
> grant is required in BOTH configurations. It is load-bearing for VISIBILITY, not just
> permission.

**If you leave `ENABLE_DISPOSITION_AUTHZ` unset (NO LONGER the sandbox config — see the flip
rider above):**
- ✅ **Drop** item 2 (the `can_invoke(mesh:startReview)` capability grant). With the gate off,
  `can_invoke_start_review` is a no-op, so the auto-starter needs no capability. This is exactly
  the hands-off witness config we ran in sandbox.
- ❌ **Keep** item 1 — the token. Gate-off does NOT remove authentication; the sensor still mints
  and presents a service token, or the review POST is rejected `401`.
- ❌ **Keep** item 3 — the reviewer audience grant. This is the trap: it is **not** an authz check
  you toggled off, it is the *routing* that decides whose queue the review lands in. Drop it and
  the review still POSTs, but `register_task` finds **zero entitled recipients** →
  `NoEntitledRecipients` → **422** → the review fails and **never reaches a human** (the loud
  zero-recipients fail-and-release, by design — better than a silent forever-suspend). Grant
  `pcn_disposition:SUSTAINMENT` to your reviewer, and `qualification` to your dispatch-actor if the
  demo shows the approve→dispatch hop.

So the minimum for the env-off demo is **token + reviewer audience grant** (+ `qualification` for
the fan-out). The env buys you skipping the *capability* grant, not the token and not the routing.

The BFF stamps the auto-starter as `approver` (the review *initiator*) — the human *reviewer* is
still resolved from the `pcn_disposition:SUSTAINMENT` audience, never from this token. When you DO
turn the gate on (to prove enforcement), an ungranted initiator gets `NOT_ENTITLED_TO_INITIATE`
(403) up front; grant item 2 to clear it. (Follow-up already noted: the review's `user_jwt` is
reused for the dispatch mint at approval time, so a long-lived-enough service credential — the
per-run client-credentials mint, not a hand-pasted static JWT — is what keeps it from going stale
mid-review.)

---

## C. Pre-demo verification — read-only, ALL must pass before you present

```
# 1. Ontology actually loaded (not just primed): engine-o classes non-empty
curl -s http://<iagent-engine-o>/classes | head -c 200            # expect a non-empty class list

# 2. Resolver resolves a KNOWN part (proves Neo4j capability graph + provider wired)
curl -s -X POST http://<iagent-engine-o>/resolve_instance -d '{"identifier":"<known-MPN>","domain":"SUSTAINMENT"}'
#    expect a hit, not UNKNOWN

# 3. Review audience granted (positive control): the reviewer sees an EMPTY-BUT-AUTHORIZED queue
#    (deny-by-default returns [] when authorized-with-nothing; a 403 = grant missing)
GET  http://<iagent-cortex-bff>/me/human_tasks   (as reviewer)    # 200 [] , not 403

# 4. The sensor is RUNNING (default is STOPPED) and its cursor is initialized
#    Dagster UI -> Sensors -> extraction_review_sensor -> toggle RUNNING
#    (or: dagster sensor start extraction_review_sensor)

# 5. MinIO buckets present: sustainment inbound + the artifacts bucket the sensor watches
mc ls <alias>/  | grep -E 'sustainment|processing-artifacts'
```
If #1/#2 fail → the load didn't happen or engine-o is stale (re-run §A, roll engine-o). If #3 is
403 → the grant didn't reconcile (re-run `task_grant_sync`). If #4 is STOPPED → the drop will
extract but no review will start.

---

## D. The demo (auto-pipeline) — you drop, the system arrives

**Beat 0 (before the audience):** §A + §B + §C all green. Sensor RUNNING. Reviewer logged into
cortex-ui showing an empty, authorized queue (nothing yet).

**Beat 1 — drop the notice.** Upload the PCN/PDN PDF to MinIO `sustainment/inbound/` (or via the
UI upload). → the inbound sensor fires → `process_document_artifact` (unstructured hi_res + crops
+ page renders) → `build_knowledge_graph` (vision → **review.json** with affected MPNs, proposed
dispositions, per-part `needs_review`). *Say to the room: "a supplier notice just arrived."*

**Beat 2 — WATCH it become a task (this is the point).** `extraction_review_sensor` sees
review.json land → builds the start_review payload **from review.json** → starts the review →
the **grouped review task materializes in the reviewer's timeline**. No POST. Arrival-as-event.
*Refresh the reviewer's view; the task is there.*

**Beat 3 — the human decides.** Reviewer opens the grouped review (evidence: crops + provenance),
accepts-all with one override, clicks **Approve** → `review_dispatched`, `resolved_count`.

**Beat 4 — the dispatch lands on the next desk.** The dispatch-actor's queue shows the
`qualification` dispatch tasks, `requested_by = reviewer`. (Assert: **no duplicate** dispatch tasks.)

**Beat 5 — the dashboard reconciles.** `GET /instances_by_property?state=dispatchQualification`
→ parts-by-state, same ruleset hash end-to-end.

---

## E. Deterministic fallback (if the live sensor path stalls in front of the audience)

The manual start is the SAME flow, guaranteed — use it if the sensor hasn't fired within ~30–60s.
Have this payload staged (impacted_parts is exactly what the sensor would have sourced from
review.json — pull it from the just-written review.json, do NOT reconstruct from the graph):
```
POST http://<iagent-cortex-bff>/reviews   (as reviewer or auto-starter)
{ "notice_id": "<doc_id from review.json>",
  "doc_type": "PCN",
  "impacted_parts": [ {affected_mpn, replacement_mpn, needs_review}, ... ],   # verbatim from review.json
  "doc_needs_review": <review.json.needs_review>,
  "domain": "SUSTAINMENT" }
```
This is the ops / re-drive path — identical downstream (Beats 3–5 unchanged).

---

## F. Honest failure is a feature, not a stumble

If the notice hits a refusal, the **Dagster run for that notice FAILS visibly** (that's the
sensor surfacing what `POST /reviews` would have returned) — and nothing silently vanishes:
- `RULES_NOT_FOUND` / `RULESET_INVALID` → the disposition ruleset isn't loaded/valid for this domain.
- `NOT_ENTITLED_TO_INITIATE` (403) → the auto-starter `svc:review-starter` lacks `can_invoke(mesh:startReview)` — grant the capability (`capability_grants.yaml`, §B). The sensor surfaces this as a failed Dagster run.
- `no_entitled_recipients` (422) → residue exists but no reviewer holds `pcn_disposition:SUSTAINMENT`, so the review would be a task nobody can act on — `register_task` refuses it and the workflow fails-and-releases (never parks). Grant the review audience (§B), re-drive.
- `REVIEW_STATE_UNSOURCED` → the notice is doc-level-needs-review but no part carries the flag
  (the tripwire — the extraction is under-sourced; do NOT paper over it).
- `NO_RESIDUE` → genuinely nothing to review (an honest non-start; the run SUCCEEDS with a skip log).

Fix the grant/ruleset, then **re-drive**: re-run the failed Dagster partition, or use §E.

---

## G. Troubleshooting pointers
- **dagster-user-code roll gotcha** — if a code-location pod rolled, its new IP stales the daemon's
  gRPC; `kubectl rollout restart` the Dagster webserver + daemon so the sensor is discovered.
- **/resolve_instance endpoint_url** — engine-o self-registers its provider URL into Neo4j at
  startup; if resolution returns UNKNOWN after a deploy, reseed the predicate endpoint_url.
- **This runbook assumes M2 is live** (renamed services `GroupedReview`/`ReviewStarter`/`DispatchItem`,
  routes `/reviews`, `/instances_by_property`, kind `grouped_review`). On a fresh work cluster,
  deploy all four from merged master (none of the m2-cutover transition risk applies) — see
  `m2-cutover-runbook.md` for the sandbox in-place cutover variant.
