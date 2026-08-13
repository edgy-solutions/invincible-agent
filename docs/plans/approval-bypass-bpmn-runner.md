---
id:         approval-bypass-bpmn-runner
status:     closed
owner:      unassigned
blocked-on: 
closed-by:  d3ef8bf
code-site:  agent_fleet/restate_analyst/main.py
repo:       invincible-agent
summary:    HIGH — RESOLVED d3ef8bf. The approval plane resolved promises with no caller identity. Gated on THREE surfaces, not the two declared: engine-a's route, the Restate approve handler, and GroupedReview.submit_decision (found while fixing the other two). Audience read from the workflow journal, never the request.
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

## RULED 2026-08-10 — gate it, and gate BOTH surfaces

**Disposition: authority writes get a real gate.** Check caller identity, ask `can_act`, and
**record the identity in the resolution** so the approval carries who made it. The cortex-bff
path already does this — so this is aligning two surfaces with a third that is already right,
not inventing a mechanism.

### THE TWO-SURFACE CAVEAT — both, or neither counts

There are **two** ungated entry points, and they are independently reachable:

| surface | site | shape |
|---|---|---|
| engine-a HTTP route | `main.py:3042` | `@app.post("/workflow/{workflow_id}/task/{task_id}/approve")` → `approve_task(...)` — **no identity dependency in the signature** |
| Restate handler | `main.py:2085` | `@bpmn_workflow.handler() async def approve(ctx, request: dict)` — called *by* the route above, and reachable **directly via the Restate ingress** |

**A fix that gates the route and leaves the handler open closes the door someone is looking at
while leaving the one behind it.** The handler is not merely the route's implementation — it is
its own entry point.

Verified 2026-08-10 by reading both sites. Acceptance for this item is that **both** are gated;
gating one is not partial progress, it is a false green — the surface still open is the one
nobody is now looking at.

---

# CLOSED 2026-08-11 — `d3ef8bf`. And the caveat above was itself one surface short.

## THE THIRD SURFACE — `GroupedReview.submit_decision`

**Acceptance corrected: it is THREE, not both.** `agent_fleet/restate_analyst/grouped_review_workflow.py:submit_decision`
resolves the grouped review's `decision` promise — **the same authority write**, on a different
runner, equally reachable from the Restate ingress. It was found while building the fix for the
two named above.

Gating two of three would have been **this packet's own two-surface caveat failing one rung up**:
the argument was right, the enumeration behind it was incomplete, and the sentence "gating one is
not partial progress, it is a false green" would have been quoted in a commit that shipped exactly
that. A caveat about missed surfaces is not itself evidence that the surfaces were all found.

### Why it was missed — the transferable part

**`submit_decision` had the most careful content validation of any handler in this service, and
none of the actor question.** It re-derives the batch server-side, validates every submitted row
against it, refuses unverified rows without an explicit override, refuses blank override reasons,
and handles the multiplayer already-settled race with a distinct terminal outcome. All of that is
about *what* is being decided. None of it is about *who* is deciding.

**Thoroughness on one axis is what hides the absence of the other.** A reviewer reading that
handler comes away reassured — correctly, about content authority — and the reassurance carries
over to a question the code never asks. This is not a lapse of attention; it is attention landing
where the evidence of care is. Content authority and actor authority are different questions, and
answering one visibly well is a reason to check the other *harder*, not a reason to relax.

Practical form: **when a handler is conspicuously careful, enumerate what it is careful ABOUT.**
The list is usually one axis long.

## The shape of the fix

| decision | why |
|---|---|
| **audience from the JOURNAL, never the request** | `can_act` needs an audience the handler cannot see (this service reaches human_tasks over HTTP, not a DB). Taking it from the request would let the caller choose the question the gate asks — the `on_behalf_of` laundering shape arriving at the approval plane. Written at all three registration sites by the code that already derived it from the definition. |
| **keyed on the PROMISE NAME** | Reuses the identity `test_promise_name_seal` already pins instead of minting a second one that could drift (grouped reviews suspend on `decision`, not `approval_{task_id}`). |
| **one home for the key**, in the leaf module both resolvers import | A reader computing a wrong key sees `None` and fails closed — **indistinguishable from "no audience journalled"**. A copy would not diverge loudly; it would fail silently in the direction nobody checks. |
| **`acted_by` on the ENVELOPE, separate from `decision.acted_by`** | Same value, two questions: authorization subject vs archived provenance. One field would mean a future change to how decisions are *attributed* silently re-aims the *gate*. |
| **identity required regardless of transport posture** | OBSERVE refuses nothing until the `ENABLE_AGENTIC_AUTH` flip. Deferring this gate to that flip would leave the approval plane open until the most-deferred change in the programme landed. |
| **denials surface as 403-with-reason, not 502** | A denial reported as an outage sends the operator hunting a broken service instead of a missing grant. 401 and 403 stay distinct: "who are you" is not "you may not". |
| **fail closed on a missing journalled audience** | Resolving anyway would be the broken-closed inversion — waving through exactly the cases the gate cannot evaluate. |

**The `cortex-bff` coupling is what kept this from being a regression.** `/act` calls the handler
directly with no identity, so gating the handler without threading `current_user.authz_id` there
would have made **the one correctly-gated path the only refused one.**

## Acceptance as met

Discriminating pairs on every surface, and **four independent break-on-purpose controls**:

| mutation | surface 1 | surface 2 | surface 3 |
|---|---|---|---|
| remove `approve` can_act | **2 FAIL** | 3 pass | 3 pass |
| remove route identity check | 5 pass | **1 FAIL** | 3 pass |
| remove `submit_decision` can_act | 5 pass | 3 pass | **2 FAIL** |
| audience from request (spoof) | **1 FAIL** | — | — |

Each reddens **only its own surface**, so no seal cross-covers another and "fixed one, believe all
three" is not available. All restored byte-identical.

Plus a **positive control** asserting the decider was actually consulted on the accept path —
without it every green half is compatible with there being no gate at all, since an ungated handler
accepts everyone.

Seal: `tests/security/test_approval_authority_gate.py` (12). Suites the gate touched: 41. Full
suite 1296 passed, with four pre-existing failures confirmed not caused by this change.

## The manifest row is corrected in the same commit

Its `justification` claimed cortex-bff was bypassed; that path was always the working precedent.
And the `gateway.py:432` citation had rotted into `ReviewStartRequest`. The row now cites
**symbols, not line numbers**, per the ruled convention — second citation to rot this month.
