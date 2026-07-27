# M2 cutover RUNBOOK — the morning coordinated roll (executable companion to m2-cutover-plan.md)

Run WITH a human (live sandbox `edge`, 4-service cutover). Preconditions: M2 merged to master in both
repos (invincible-agent `1828fd9`, cortex-ui `bcf52f7`) + images built (`gh run list --workflow=build-containers.yml`
green for engine-a/o/cortex-bff; cortex-ui `build.yml` green). Deploys: `iagent-engine-a` (restate_analyst),
`iagent-engine-o` (ontology_service), `iagent-cortex-bff`, `iagent-cortex-ui`. Restate admin `iagent-restate:9070`,
ingress `:8080`. Do the steps IN ORDER; the transition is the only incoherent state — keep it short.

## 0. Pre-flight (read-only)
```
kubectl get deploy -n sandbox | grep -E 'engine-a|engine-o|cortex-bff|cortex-ui'   # all 1/1 before starting
# confirm images built since the merge (else wait for CI):
gh run list --workflow=build-containers.yml --limit 3
```

## 1. Drain in-flight Restate invocations (old service names)
Old names (`PcnGroupedReview`, `PcnReviewStarter`, `PcnDispatchItem`) vanish on cutover; any in-flight
invocation would orphan. Confirm none / cancel them:
```
kubectl exec -n sandbox iagent-restate-0 -- restate invocations list 2>/dev/null | grep -iE 'PcnGroupedReview|PcnReviewStarter|PcnDispatchItem' || echo "none in-flight"
# for each id: kubectl exec -n sandbox iagent-restate-0 -- restate invocations cancel <id> --yes
```

## 2. Roll all four services TOGETHER
```
kubectl rollout restart -n sandbox deploy/iagent-engine-a deploy/iagent-engine-o deploy/iagent-cortex-bff deploy/iagent-cortex-ui
for d in engine-a engine-o cortex-bff cortex-ui; do kubectl rollout status -n sandbox deploy/iagent-$d --timeout=180s; done
```
(If any dagster code-location IP staled — not expected here — restart webserver+daemon per
[[project_dagster_usercode_roll_gotcha]].)

## 3. Re-register the renamed Restate deployment (CRITICAL — rolling the pod alone leaves the OLD handler set)
engine-a serves the Restate SDK (services `GroupedReview`, `ReviewStarter`, `DispatchItem`). Force Restate
to re-discover the renamed service set. Confirm the engine-a restate SDK URI first (the mount serving
restate.app — engine-a svc is `iagent-engine-a:8081`; the SDK endpoint is where `/restate` is mounted):
```
kubectl exec -n sandbox iagent-restate-0 -- sh -c 'curl -s -X POST http://localhost:9070/deployments -H "content-type: application/json" -d "{\"uri\":\"http://iagent-engine-a:8081\",\"force\":true}"' | head -c 400
# then confirm the new services are registered:
kubectl exec -n sandbox iagent-restate-0 -- sh -c 'curl -s http://localhost:9070/services' | grep -oE 'GroupedReview|ReviewStarter|DispatchItem' | sort -u
```
Expected: `DispatchItem`, `GroupedReview`, `ReviewStarter` present; NO `Pcn*`.

## 4. Verify the capability-graph re-registration for /resolve_instance
engine-o self-registers its `mesh:resolveInstance` provider endpoint_url into Neo4j on startup. Confirm it
now ends `/resolve_instance` (was `/resolve_pcn_instance`):
```
kubectl exec -n sandbox iagent-neo4j-0 -- cypher-shell -u neo4j -p changeme-neo4j-sandbox \
  "MATCH ()-[r:VERB {iri:'mesh:resolveInstance'}]->() RETURN r.endpoint_url" 2>&1 | grep -i resolve
```
If it still shows `/resolve_pcn_instance`, reseed: run `scripts/seed_sandbox_predicates.py` (its endpoint_url
is updated by the M2 rename). The `/resolve` fan-out finds the provider via this URL — if stale, resolution breaks.

## 5. Pre-rehearsal cleanup (ALSO the dedup-marker mitigation — m2-cutover-plan.md option A)
Clears pre-rename dispatches so the renamed `DispatchItem` objects start clean (no double-mint) AND the demo
mints fresh:
```
# cancel bob's residual dispatch tasks + clear IPCN25300X / PCNBFFSEAL01 disposition state + reset the
# review workflow keys. (Use the pre-rehearsal cleanup from project_pcn_driver_arc / the five-beats exhibit.)
```

## 6. Five-beats loop re-witness (the acceptance — this IS the rehearsal's first pass)
Token: `alice`/`alice`, client `cortex-ui`, realm `invincible-agent`. Run from `iagent-restate-0`:
```
# 1. start a review through the BFF's RENAMED route:
POST iagent-cortex-bff:8090/reviews   {notice_id, impacted_parts...}   -> STARTED + workflow_id
# 2. alice /me/human_tasks -> grouped review task, kind "grouped_review" (was pcn_grouped_review), audience disposition_review:SUSTAINMENT
# 3. fetch batch: GET iagent-cortex-bff:8090/reviews/{workflow_id}/batch (was /pcn/reviews/...)
# 4. resolve via /human_tasks/{id}/act accept-all(+1 override) -> review_dispatched, resolved_count
# 5. bob /me/human_tasks -> QUALIFY (pcn_disposition) dispatch tasks, requested_by alice   [ASSERT: no DUPLICATES]
# 6. dashboard: GET iagent-cortex-bff:8090/instances_by_property?state=dispatchQualification (was /pcn/parts_by_state)
#    -> INSTANCES_BY_PROPERTY payload, same ruleset hash end-to-end
```
**ACCEPTANCE:** every leg green on the renamed services + NO duplicate dispatch tasks (the dedup catch,
closed by step 5). If green → M2 is live + coherent; the demo runs on the renamed mechanism.

## Rollback (if a leg fails)
The images are `:latest`; roll back by `kubectl rollout undo` each of the 4 deploys TOGETHER + re-register
the old deployment. Because it's a coordinated set, roll back as a set. The branch/merge stays; investigate,
re-roll. (Work-deploy has none of this transition risk — fresh cluster, all-4-from-merged-master.)
