---
id:         undeclared-routes
status:     open
owner:      agent
blocked-on: TOPAZ_DIRECTORY_URL is not wired into engine-o's deployment — the gate below fails CLOSED without it, so the env must land with the ENABLE_AGENTIC_AUTH flip, not after. Everything else is done: dispositions given, /workflow/start retired (410, 2026-08-11), ALL 12 ROWS DECLARED (2026-08-12), and the two engine-o WRITE residuals CLOSED endpoint-side 2026-08-13 (can_invoke on the single decider, discriminating pair sealed, break-on-purpose verified; both rows now class: gated).
closed-by:  
repo:       invincible-agent
summary:    RULED 2026-08-10 — the four dispositions are given and promoted to the standing rule [[gate-class-follows-the-effect]]. Three dependents unblocked. Residual: /workflow/start is verify-then-disable, and 2 of 5 repos are still unswept.
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

> **RESOLVED 2026-08-11 — the question below is NO LONGER UNRATIFIED.** It was answered on
> 2026-08-10 (see *RULED* further down) and promoted to `[[gate-class-follows-the-effect]]`. The
> three dependents named here are unblocked and inherit their columns from the law.
>
> **This banner exists because the header said otherwise for a day.** `status: blocked-on-human ·
> blocked-on: gate-class judgment per route` survived below a body that already contained the
> ruling — and survived an agent *executing against* that ruling. See ADR-0040's 2026-08-11
> amendment; the section is left standing rather than rewritten because the dependents' reasoning
> is still the record of why the ruling mattered.

It is no longer only about twelve rows. **Three separate items were waiting on the same question:
is in-cluster reachability an acceptable gate?**

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

### `/workflow/start` — EXECUTED 2026-08-11, the condition was met and nobody noticed

> **The gate cleared and the item did not move.** 5 of 5 repos swept, zero consumers. The
> disposition below had been waiting on a condition that was already satisfied — the same
> header-outlives-the-fact shape ADR-0040's amendment is about, one field over.

**Done:** `main.py` `start_workflow` returns **410 GONE** unless `ENABLE_WORKFLOW_START=true`.
Manifest row moved to `class: retired` alongside `/bpmn/save` and `/bpmn/catalog`. Pinned by
`tests/test_workflow_start_disabled.py` (10 pins, including the re-enable path).

**Why 410 and not deletion.** Verification bounds the risk of disabling; a **self-explaining
refusal bounds the cost of having been wrong**. A 404 is indistinguishable from a bad ingress or a
typo and sends a caller after the wrong problem — which would be the silent-refusal class arriving
by the very door this decision closed. The 410 body names the ruling, this packet, and the
re-enable switch, and a call while disabled is logged as the sweep's falsification signal.

**The flag is a falsification lever, not a supported configuration.** Its siblings were retired
because a replacement landed; this one is retired because nothing calls it. If a real consumer
surfaces, the disposition reopens *here* — it does not get switched on in one environment and
forgotten, which would recreate the undeclared-route state the item exists to remove.

**The posture is announced at startup** (`workflow/start: DISABLED (default) [engine-a]`), so an
operator can learn which state a pod is in without calling a route they have been told not to use
— `[[flag-effects-must-be-observable]]`.

<details><summary>The original ruling, kept for the reasoning</summary>

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

</details>

## ALL 12 ROWS DECLARED — 2026-08-12, and the declaration CHANGED TWO OF THEM

`test_endpoint_gating_manifest` is 15/15. The three red `test_every_source_route_is_declared`
cases are green, and master drops from four known failures to one.

**The classes were NOT copied from this packet's proposals.** Two diverged, both because
`[[gate-class-follows-the-effect]]` landed *after* the proposals were written:

* **`/write_item_state` and `/write_decision_record` are `ungated_by_accident`, not `internal`.**
  This packet proposed all six engine-o routes as `internal`. The human's disposition accepted
  *"the READ/ORCHESTRATION routes"* — which is four of the six, not all of them. The law is
  explicit that effect and integrity writes are **never** acceptable on in-cluster reachability
  alone, so the two writes are FINDINGS. A proposal written before a rule does not get to
  outrank it.
* **`/lineage_by_platform` is `internal`, and it is only written down because the exposure check
  was finally run.** This packet proposed it at LOW confidence and said so: *"should be checked
  against how the wrapper is actually reachable before it is written down."* Checked — the
  chart's Ingress covers cortex-ui, cortex-bff, dagster and electric only, so datahub-wrapper is
  ClusterIP with no ingress. **Declaring it on the route's shape alone would have been the
  presence-check defect** this manifest's own amendment describes.

The five cortex-bff rows landed as proposed at `gated`, verified per route — the only class in
this file earned by verification rather than by reachability.

**A guard caught a real mistake during this work**, worth recording because it is why the file is
trustworthy: `/lineage_by_platform` was first written into the `neo4j_expert` block, and
`test_no_stale_manifest_routes` failed with *"stale manifest routes (not found in source)"*. The
manifest does not merely require rows to exist — it requires them to exist **where the route
does**.

### What the declaration did NOT do

It classified the two writes; it did not gate them. `/write_item_state`'s caller side was minted
2026-08-11 (`svc:review-starter`, correct by design), and the endpoint still authenticates nobody
— the two halves were always meant to land together. `/write_decision_record` is the quieter of
the pair and the worse for audit: its caller DEGRADES, so under REQUIRE the corpus grows holes
routinely and nothing announces it.

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
