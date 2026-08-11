---
id:         approval-bypass-bpmn-runner
status:     open
owner:      unassigned
blocked-on: 
closed-by:  
code-site:  agent_fleet/restate_analyst/main.py
repo:       invincible-agent
summary:    HIGH (declared, unresolved) — BPMNWorkflowRunner/approve resolves the approval promise with NO caller identity. In-cluster only today; that mitigation does not travel to the work cluster.
---

# Approval bypass on `BPMNWorkflowRunner` — declared HIGH, unresolved, and until now unindexed

**This is not a new discovery.** It is rated `FINDING (high)` in
`docs/architecture/endpoint_gating_manifest.yaml`, and a second warning sits in
`src/iagent/gateway.py` telling the reader it must not be assumed closed by the BPMN retirement:

> *the unauthenticated workflow-APPROVE path (BPMNWorkflowRunner/approve) is a **SEPARATE finding on
> the KEPT runner** — it is NOT addressed here and must not be assumed-closed by this retirement.*

**Both notices were written; neither was indexed.** It is filed here because a HIGH security finding
living only inside a YAML and a source comment is the decided-and-unindexed class at its most
expensive — and unlike the rules that class usually swallows, this one is a live defect.

## What is actually true, verified 2026-08-10

**The Restate handler cannot check identity, because identity is not in its request.**
`main.py:2085` — `async def approve(ctx, request)` reads `task_id`, `status`, `comments`, derives
`promise_name`, and resolves the durable promise. There is no caller field. **Nothing is bypassed by
mistake; there is simply nothing to check.**

**engine-a's HTTP route is ungated.** `main.py:3042` —
`@app.post("/workflow/{workflow_id}/task/{task_id}/approve")`, signature
`approve_task(workflow_id, task_id, req: ApprovalRequest)`. No `Depends`, no `current_user`.
`ApprovalRequest` is `status` + `comments` only.

**Effect:** resolving the promise wakes the paused `UserTask` and the workflow resumes. Any caller who
can reach either surface can approve any paused human task, as anyone, with no record of who did it.

### What is NOT true — a correction to the manifest's own text

The manifest says *"Comment claims cortex-bff can_act gates it, but this HTTP route (and the Restate
BPMNWorkflowRunner/approve handler at gateway.py:432) bypasses that."* Read today:

- **The cortex-bff path IS gated.** `gateway.py:~1220-1233` resolves through `can_act` and threads
  `current_user.authz_id` into the call; the code even comments *"AUTHORIZED caller reaches here
  (can_act passed above)"*. The BFF is not the hole.
- **`gateway.py:432` no longer points at the approve path** — that line is now inside
  `ReviewStartRequest`. The citation drifted; the *finding* did not. (Source-anchored citations rot;
  this is the second time that has cost a reader time this week.)

So the bypass is **two surfaces, not three**: engine-a's ungated HTTP route, and direct invocation of
the Restate ingress. The gated BFF path is the one that behaves.

## Severity and its expiry date

**Not a fire tonight.** `iagent-restate` and `iagent-engine-a` are both `ClusterIP`, and neither
appears among the cluster's six Ingress objects (`datahub`, `cortex-bff`, `cortex-ui`, `dagster`,
`keycloak`, `minio`). Reachability is in-cluster only.

**The mitigation does not travel.** "In-cluster only" is a real control exactly while you author every
pod in the cluster. At the work deploy that assumption weakens, and it is the same unratified posture
question that `undeclared-routes` is holding — see its dependents. **This item should be resolved
before, not after, the approval plane runs anywhere you do not own every workload.**

It is also worth stating what makes this different from engine-o's six `internal` routes: those expose
and mutate *content*. This one resolves an **authority** decision — the promise it wakes is the human
approval that the entire trust architecture treats as the enforcement point. A system whose thesis is
*one authority, checked at the enforcement point* has an approval plane that checks nobody.

## The work

1. **Decide the shape**: thread caller identity into the `approve` request and check `can_act` at the
   handler (making the Restate surface self-defending), or make engine-a's route the only door and
   gate it there. The first is the one-authority answer; the second is cheaper and leaves the Restate
   surface trusting the cluster.
2. Whichever is chosen, the approval must record **who** — an approval with no actor is unauditable,
   and the `requested_by`/`acted_by` split already exists to carry it.
3. Seal it in the shape this repo uses for gates: a discriminating pair (authorized caller approves;
   unauthorized caller is refused), not a smoke test.
4. Correct the manifest row: the cortex-bff clause is wrong, and the `gateway.py:432` citation is
   stale.

## Related

- `undeclared-routes` — the unratified in-cluster-posture decision this finding's mitigation rests on.
- `retire-inline-task-loop` — same runner; that item's security read (2026-08-10) established the
  reachability facts reused above.
