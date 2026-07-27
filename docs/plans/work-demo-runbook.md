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

All three principals below get their entitlement through `policy/task_grants.yaml` +
`task_grant_sync` (validate → reconcile → readback → prune). Deny-by-default means an ungranted
principal sees an **empty authorized queue**, not an error — verify the ALLOW path positively (§C).

| principal (symbolic) | needs | audience / capability |
|---|---|---|
| **reviewer** | to see + approve the grouped review | task audience `pcn_disposition:SUSTAINMENT` |
| **dispatch-actor** | to see + act the dispatched qualification tasks | task audience `qualification` |
| **auto-starter** (the sensor's `REVIEW_STARTER_TOKEN` identity) | to START reviews AND mint dispatch tasks | a valid identity + the dispatch mint capability |

**The auto-starter identity is the one new grant this pipeline needs.** The sensor authenticates
to cortex-bff `/reviews` as this service identity; the BFF stamps it as `approver` (the review
*initiator* — the human *reviewer* is still resolved from the `pcn_disposition:SUSTAINMENT`
audience, not this token). Because the review's `user_jwt` is reused for the dispatch mint at
approval time, this identity must also carry the dispatch-mint capability. Grant it in the same
git-rails pass. (Follow-up already noted: `user_jwt` staleness for auto-started reviews — a
service token that doesn't expire mid-review is the clean fix.)

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
- `NO_ENTITLED_ACTION` → residue exists but no reviewer holds `pcn_disposition:SUSTAINMENT` (grant it, §B).
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
