# M2 cutover plan — the coordinated roll (the only incoherent state is the transition)

Branch `m2-extraction-sort` is coherent; master is coherent; the **transition** is the sole incoherent
state, and it lands on the same cluster the demo runs on. This is the most operationally complex deploy of
the arc: a four-service simultaneous roll + a Restate drain + a capability-graph re-registration.

## Recommendation: roll BEFORE the demo, as its own focused window, with a full loop re-verification after
Rehearsing on master then cutting over post-demo certifies images you're about to discard, and every
rehearsal fix lands twice. Roll first; the **five-beats loop re-witness IS the rehearsal's first pass**
(start_review → grouped review → resolve → fan-out → dashboard, re-run on the renamed services). The
demo-risk counterargument is answered by that re-verification being the gate.

**Merge-vs-roll:** merging to master rebuilds the four `:latest` images. The running sandbox pods do NOT
auto-pull, BUT any pod reschedule between merge and the coordinated roll pulls a new image while its peers
stay old = the incoherent transition, unbidden. So keep the merge→roll gap SHORT, or do the roll as the
immediate next window.

## The renames orphan DURABLE Restate objects, not just in-flight workflows — the dedup catch
`PcnDispatchItem` → `DispatchItem` renames the Restate **VirtualObject service**. Those keyed objects hold
the **dedup markers** — the exactly-one-task guarantee's memory (the kill-seal property). After the rename,
a re-fired dispatch for an already-dispatched `(notice × part)` addresses a FRESH object under the new
service name, finds NO marker, and **mints a second task** — the exactly-one property silently voided for
every item dispatched pre-cutover. (The graph-state write is delete-then-insert, so the STATE is safe; it
is the task-MINT that can double.) The three qualification tasks in bob's queue are exactly this class.

**Mitigation (pick one; option A is already the plan):**
- **A — pre-rehearsal cleanup subsumes it (RECOMMENDED).** The named pre-rehearsal cleanup already clears
  IPCN25300X + PCNBFFSEAL01 state + tasks and resets the review workflow keys. Run it AS PART OF the
  cutover, AFTER the roll: there are then zero pre-rename dispatches to double, and the renamed
  `DispatchItem` objects start clean. Cleanest for the demo.
- **B — re-seed keys under the new name** (only if pre-rename durable state must survive): copy the old
  `PcnDispatchItem/<key>` dedup markers to `DispatchItem/<key>`. Heavier; unnecessary for the demo.
- **C — declare pre-rename dispatches re-dispatchable-by-design** and cancel the old tasks. Equivalent to A
  for the demo.

## Roll sequence (the window)
1. **Drain** in-flight `PcnGroupedReview` / `PcnReviewStarter` invocations (`restate invocations cancel`),
   or confirm none in-flight.
2. **Roll all four together:** engine-a (restate_analyst) + engine-o (ontology_service) + cortex-bff +
   cortex-ui. `kubectl rollout restart` each; wait all Ready. (Per [[project_dagster_usercode_roll_gotcha]]
   if any dagster code-location IP staled, restart webserver+daemon — not expected here.)
3. **Re-register the renamed Restate deployment** with Restate (`POST restate:9070/deployments {uri,force:true}`)
   so the new service names (`GroupedReview`, `ReviewStarter`, `DispatchItem`) are in the routing set —
   rolling the pod alone leaves the old handler set (the get_batch re-register gotcha, seen before).
4. **Verify the capability-graph re-registration:** engine-o self-hosts `/resolve_instance` (was
   `/resolve_pcn_instance`) and self-registers its `endpoint_url` into Neo4j on startup. Confirm the live
   graph's `mesh:resolveInstance` provider `endpoint_url` now ends `/resolve_instance` (else the `/resolve`
   fan-out won't find the provider). Reseed via `seed_sandbox_predicates.py` if the self-reg didn't update it.
5. **Pre-rehearsal cleanup** (mitigation A): clear IPCN25300X + PCNBFFSEAL01 state/tasks, reset wf keys.
6. **Full loop re-witness** (the rehearsal's first pass) on the renamed services: start_review → grouped
   review batch → resolve (accept-all + one override) → fan-out mints QUALIFY (`pcn_disposition`) tasks to
   bob → dashboard `/instances_by_property` returns the parts. Assert no duplicate dispatch tasks (the
   dedup catch, closed).

## Work-deploy note
At work the four-service set deploys together from the merged master by construction (fresh cluster, no
in-flight durable state to orphan, capability graph seeded from scratch) — the dedup-transition and drain
concerns are sandbox-cutover-only. See [[project_work_deploy_runbook]].
