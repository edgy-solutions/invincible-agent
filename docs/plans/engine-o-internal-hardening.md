---
id:         engine-o-internal-hardening
status:     parked
owner:
blocked-on:
trigger:    the cluster stops being closed — a SHARED work cluster, any workload you did not author, or a network-policy change
closed-by:
repo:       invincible-agent
summary:    Engine-o's internal read/orchestration routes are accepted at current posture. Fires when in-cluster reachability stops being an acceptable gate.
---

# Engine-o internal hardening — parked on a condition, not a queue

**Ruled 2026-08-10: acceptable as-is.** Engine-o's read and orchestration routes — resolution,
planning, predicate search, class listing — are accepted at their current posture, because the
mitigation that makes them acceptable is real today: **the cluster is closed.** Every caller is
a workload this team authored, on a network nobody else is on.

This packet exists so that acceptance is **conditional and legible**, rather than a decision that
quietly becomes permanent.

## THE TRIGGER — this is the point of the packet

**Fires when the cluster stops being closed.** Concretely, any one of:

* the work cluster becomes **shared** — another team's workloads land in it;
* **any workload you did not author** runs in the namespace (a vendor sidecar, an ops agent, a
  third-party operator);
* a **network-policy change** widens what can reach engine-o.

Each is a real, observable event. None is "someday". That is deliberate: per the bank rule,
**every banked item gets a named trigger or deadline at bank-time**, because a parked item whose
firing condition is invisible is one nobody will ever un-park — indistinguishable from forgotten.

## Why in-cluster reachability is an acceptable gate *today* and not in general

It is a **perimeter argument**: safety resting on where the caller happens to run rather than on
what the caller can prove. This repo has retired that argument three times — `MESH_DEV_TOKEN`'s
"you are running within the secured JupyterHub environment", `core/authz.py` deferring signature
verification to the gateway, and the DA read path trusting a payload field.

It is accepted here anyway, for one reason: **the perimeter is currently real and small**, and
the alternative — gating every internal read — costs more than the risk it removes while the
closure holds. The moment the closure stops holding, the argument reverts to the one this repo
rejects, and this item fires.

## What the work would be

Not enumerated here on purpose — the shape depends on what broke the closure. A shared cluster
argues for transport auth on the read routes; an unauthored sidecar argues for network policy
first. Scoping before the trigger fires would be designing against a hypothetical.

## What is NOT in this packet

`/write_item_state` — an **effect** write, not an internal read. Ruled separately: it gets a gate
class and its minted caller together (`endpoint-gating-undeclared-routes-recommendation.md`).
The distinction is the ruling's spine: **authority and effect writes get gates now; internal
reads are accepted under a closure that is watched.**
