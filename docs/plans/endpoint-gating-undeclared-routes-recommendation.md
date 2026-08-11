---
id:         undeclared-routes
status:     blocked-on-human
owner:      human
blocked-on: gate-class judgment per route
closed-by:  
repo:       invincible-agent
summary:    12 routes undeclared in the gating manifest, incl. decision-plane writes. BLOCKING THREE OTHER ITEMS — all wait on one unratified call: is in-cluster reachability an acceptable gate?
---

# The 12 undeclared routes — evidence and a RECOMMENDATION (not a decision)

`tests/test_endpoint_gating_manifest.py` has three reds. **The test is not broken** — it is correctly
reporting routes that exist in source and carry no row in the endpoint-gating manifest. Declaring a
route's gate class is a security judgment, and mislabelling one as `gated` is exactly the false-green
this repo forbids, so this file gives the **evidence** and a proposed class for each. The decision is
the architect's.

Every "gated" claim below was read from the route's actual dependency list, not inferred from its
name or its neighbours.


## INTERSECTION with transport-flip — `/write_item_state`, one specific line

**Noted 2026-08-10 in both packets, because a defect visible from two items gets fixed twice or
not at all.**

`agent_fleet/restate_analyst/dispatch_driver.py:247` calls engine-o `/write_item_state` **with no
credential**, and `/write_item_state` is one of the 12 undeclared routes in this packet. So the
same endpoint is simultaneously:

* an **unminted caller** (transport-flip's list — one of 11 that STOP under REQUIRE), and
* an **unclassified gate** (this packet — no identity/gate/class row).

Worse than either alone: `_fail_terminal_on_4xx` runs *before* `raise_for_status`, so a 401 is
classed **terminal** and Restate will not retry. The disposition write fails permanently.

Whoever classifies this route should know a caller is already broken against it; whoever mints
that caller should know the route's gate class is undecided. **Neither fix is complete without
the other.**

## cortex-bff (`src/iagent/gateway.py`) — 5 routes

All five carry `current_user: User = Depends(get_current_user)`, verified per route:

| route | line | evidence | proposed class |
|---|---|---|---|
| `POST /reviews` | 510 | `Depends(get_current_user)` | `gated` |
| `POST /triage_tasks` | 332 | `Depends(get_current_user)` | `gated` |
| `GET /instances_by_property` | 944 | `Depends(get_current_user)` | `gated` |
| `GET /notices/{notice_id}/provenance` | 904 | `Depends(get_current_user)` | `gated` |
| `GET /reviews/{workflow_id}/batch` | 639 | `Depends(get_current_user)` | `gated` |

Confidence: **high**. These are the BFF's authenticated surface and the dependency is explicit in
each signature. `/reviews/{workflow_id}/batch` additionally filters on the caller's own pending
queue (existence-oracle safe), and `POST /reviews` stamps the approver from the token rather than
the body.

## engine-o (`agent_fleet/ontology_service/main.py`) — 6 routes

**None of these has any auth dependency.** Verified: zero `Depends` / `current_user` / token lines
within each route's definition.

| route | auth dep | exposure | proposed class |
|---|---|---|---|
| `POST /write_item_state` | none | ClusterIP, no ingress | `internal` — **see the flag below** |
| `POST /resolve_instance` | none | ClusterIP, no ingress | `internal` |
| `POST /policy_rules` | none | ClusterIP, no ingress | `internal` |
| `POST /operable_subjects` | none | ClusterIP, no ingress | `internal` |
| `POST /instances_by_property` | none | ClusterIP, no ingress | `internal` |
| `POST /write_decision_record` | none | ClusterIP, no ingress | `internal` |

Confidence: **medium, and the medium is the point.** `internal` is only honest if the cluster
boundary is accepted as the trust boundary — the service is `ClusterIP` with no ingress, so nothing
outside can reach it, but **any in-cluster pod can call these freely**. That is a posture, not an
accident, and it should be ratified as one rather than inherited by default.

### The row that deserves more than a class

**`POST /write_item_state` is the dispatch effect endpoint** — the one the disposition fan-out calls,
and the one the autonomous path now reaches. Its gate lives entirely on the **caller** side
(`can_invoke(mesh:dispatchDispositions)`, checked by the executor before dispatch); the endpoint
itself authenticates nobody. So the authority model is: *the mesh decides who may cause the effect,
and the effect endpoint trusts the mesh.*

That is coherent, and it is also a single point of failure with no defence in depth: an in-cluster
caller that bypasses the executor writes item state directly, with no capability check anywhere in
the path. Worth an explicit decision — accept it as the internal-trust posture, or give the endpoint
its own service-identity check so the gate is enforced at both ends.

## datahub-wrapper (`agent_fleet/datahub_wrapper/main.py`) — 1 route

| route | line | auth dep | proposed class |
|---|---|---|---|
| `POST /lineage_by_platform` | 972 | none (`async def lineage_by_platform(req: LineageByPlatformRequest)`) | `internal`, pending an exposure check |

Confidence: **low.** Read-only catalogue lineage, no auth dependency. I could not confirm the
service's exposure the way I could for engine-o, so the class is proposed on the route's shape alone
and should be checked against how the wrapper is actually reachable before it is written down.

## This item has accumulated dependents — three, as of 2026-08-10

It is no longer only about twelve rows. **Three separate items are waiting on the same unratified
question: is in-cluster reachability an acceptable gate?**

| dependent | what it inherits |
|---|---|
| engine-o's six `internal` routes (in this file) | `internal` is honest only if the cluster boundary is the trust boundary |
| `retire-inline-task-loop` | client-supplied `definition`, reachable in-cluster only — cleanup or fix depends on this call |
| `approval-bypass-bpmn-runner` | **HIGH** — the approval promise resolves with no caller identity; in-cluster-only is its entire mitigation |
| `/workflow/start` (engine-a, added below) | ungated in code, `consumers: [none-found]`, in-cluster only |

**The last one is why the decision has a deadline.** In-cluster-only is a real control precisely while
you author every pod. At the work deploy that weakens — and the item riding on it is an approval plane
that checks nobody.

### The pattern is NOT platform-confined — first cross-repo instances, 2026-08-10

The `dag-tools` sweep (repo 3 of 5) found the same shape in another repo:
`[[dag-tools-broker-register-unauthenticated]]` (an unauthenticated routing-table write) and
`[[dag-tools-gateway-unverified-subject]]` (a data route that never verifies its bearer and takes
its authz subject from a header). **Both are filed as their own items and inherit this item's
per-class ruling as precedent — neither reopens it.**

Their existence is the argument for reading that ruling as a **standing rule** rather than a
one-time disposition of twelve known routes: the next instance did not come from this codebase,
and the one after that will not either.

### Row added 2026-08-10 — `POST /workflow/start` (engine-a)

| route | auth dep | manifest class | note |
|---|---|---|---|
| `POST /workflow/start` | **none** — `start_workflow(req: WorkflowStartRequest)`, no `Depends` | `delegates` | `consumers: [none-found]`. Justified as delegating to per-step gates (service-task 401/403, `direct_call` `can_invoke`, `spo_operation` verify) — coherent, and those gates are real. Belongs in this decision, not in separate treatment. |

## What I did not do

Write any of these into the manifest. The test stays red until the classes are ratified, which is
the correct state: a red that names real undeclared routes is doing its job, and silencing it with
guessed classes would convert a security question into a green tick.

## RULED 2026-08-10 — the human's dispositions

### `/write_item_state` — gate class AND minted caller, together

It sits in this packet (unclassified gate) and in `unminted-caller-enumeration` (unminted
caller). **Fixed as one change, not two.** The `_fail_terminal_on_4xx` amplifier is why: a 401
there is classified terminal, so Restate will not retry — a permanent failure of the disposition
write. Gating without minting converts a working path into a permanently broken one.

### Engine-o internals — ACCEPTABLE AS-IS, with a hardening item filed

The read/orchestration routes engine-o exposes to in-cluster callers are accepted at their
current posture. The residual risk is filed as `engine-o-internal-hardening` with a **trigger**,
not a queue position — per the bank rule, a parked item with no firing condition rots.

### `/workflow/start` — DISABLE, GATED ON A CROSS-REPO CONSUMER SWEEP

`consumers: [none-found]` is a **static-analysis result over the repos swept so far**, and four
repos are unswept — `dag-tools` and `cortex-ui` are both plausible callers of a workflow-start
endpoint.

So the sequence is **verify no consumer across all repos, THEN disable** — never
disable-and-discover, which manufactures exactly the silent-refusal class this arc has spent a
week eliminating.

**Cheap, because the sweep is already queued**: `unminted-caller-enumeration` needs the same
four-repo read. **Same read, two answers.** If it confirms zero consumers, disable; if it finds
one, the route stops being unused and gets classified like any other action route.

**This item unblocks on the strength of these four dispositions.**

## PROMOTED TO A STANDING RULE — 2026-08-11

The per-class ruling above is no longer a disposition of twelve routes. It is
`[[gate-class-follows-the-effect]]`, and **this packet is its first application, not its home.**

**What promoted it:** two `dag-tools` findings — a different repo, sharing no code and not even
depending on the mesh SDK — landed in its columns *without amendment*. A ruling that resolves
cases it was not drafted against is a rule; one that only resolves its own is a disposition.
Leaving it here would mean every cross-repo instance reopens a question that took an evening to
settle.

**Consequence for future findings:** classify against the law, file as your own item citing it,
and **do not reopen this packet.** Its scope is the twelve platform routes; widening that to
"anywhere the pattern appears" is what makes an item's boundary meaningless.

**Not restated above, deliberately** — one home, not two. The law carries the columns, the closure
condition on internal reads (which *expires* at the work deploy), and the application procedure.
