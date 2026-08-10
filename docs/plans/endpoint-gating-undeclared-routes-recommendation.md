---
id:         undeclared-routes
status:     blocked-on-human
owner:      human
blocked-on: gate-class judgment per route
closed-by:  
repo:       invincible-agent
summary:    12 routes undeclared in the gating manifest, incl. decision-plane writes.
---

# The 12 undeclared routes — evidence and a RECOMMENDATION (not a decision)

`tests/test_endpoint_gating_manifest.py` has three reds. **The test is not broken** — it is correctly
reporting routes that exist in source and carry no row in the endpoint-gating manifest. Declaring a
route's gate class is a security judgment, and mislabelling one as `gated` is exactly the false-green
this repo forbids, so this file gives the **evidence** and a proposed class for each. The decision is
the architect's.

Every "gated" claim below was read from the route's actual dependency list, not inferred from its
name or its neighbours.

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

## What I did not do

Write any of these into the manifest. The test stays red until the classes are ratified, which is
the correct state: a red that names real undeclared routes is doing its job, and silencing it with
guessed classes would convert a security question into a green tick.
