---
id:         dag-tools-broker-register-unauthenticated
status:     open
owner:      human
blocked-on: gate assignment — inherits undeclared-routes' per-class ruling, integrity-write column
closed-by:  
code-site:  dag_tools/central_gateway/main.py:75
repo:       dag-tools
summary:    Unauthenticated routing-table write — /api/v1/internal/register takes broker_url from the body and repoints any URN. Integrity write, so NOT acceptable on in-cluster reachability alone. First cross-repo instance of the undeclared-routes pattern.
---

# `/api/v1/internal/register` — an unauthenticated write that repoints the data plane

Filed as its own item rather than folded into `undeclared-routes`, per the ruling of 2026-08-10.
It **inherits** that item's per-class ruling as precedent; it does not reopen it.

## Why it is filed separately — the ruling, recorded so it is not re-litigated

1. **Different repo.** `undeclared-routes` scopes the platform's 12 routes. Absorbing a dag-tools
   route would make that item's boundary meaningless — and the `repo:` field exists precisely so
   cross-repo items are visible as such.
2. **Different owner and different fix.** `undeclared-routes` is *one ruling assigning gate
   classes to a known set*. This is *one route needing one gate* — the shape
   `approval-bypass-bpmn-runner` already has.
3. **`undeclared-routes` just closed on its per-class ruling.** Reopening it to absorb a new
   instance would undo a decision that took an evening to reach.

## What is true — read 2026-08-10

`central_gateway/main.py:75` — `@app.post("/api/v1/internal/register")`, signature
`register_broker(payload: RegisterPayload)`. **No `Depends`, no credential, no caller check.**

The handler takes `broker_url` and `asset_urns` **from the request body** and executes
`SETEX mesh_route:{urn} 300 {broker_url}` for each (`main.py:84-91`).

**Effect: any caller who can reach the gateway can repoint any URN at any URL.** The gateway then
POSTs the resolve to that URL (`main.py:307`) and returns the ticket it receives — `physical_uri`
and `credentials` included — to the requesting user.

The broker's `/api/v1/internal/resolve` (`domain_broker/main.py:360`) is likewise ungated; its
docstring says *"Called ONLY by the Central Gateway"*, which is a statement of intent with nothing
enforcing it.

## The gate class it lands in

Per `undeclared-routes`' per-class ruling: **an integrity write** — it repoints routes. It is
neither an authority write nor an internal read, so it lands in the
**"not acceptable on in-cluster reachability alone"** column.

Topaz still gates the URN, so this is **not** an entitlement bypass. What it yields is:

* **Integrity** — serve an *entitled* user a ticket pointing at attacker-chosen storage.
* **Availability** — overwrite every route with a dead URL; see the TTL severity below.

## The severity the "degrades" reading hides

The caller side of this route (`domain_broker/main.py:247`) is classified DEGRADES because both
call sites catch and log. That reading is right and it undersells the outcome.

The broker's own comment (`main.py:259-263`) explains the design: the gateway holds `mesh_route:*`
on a **300-second TTL**, and the broker re-pushes every **120s** so that one missed push cannot
empty it. **That is a hiccup mitigation being relied on against a persistent refusal.** Any
condition that blocks every push — not a hiccup — empties the routing table one TTL later, and the
gateway then answers **404 "No active domain broker found"** for every asset.

A total data-plane outage that reports as *not found*. Loud in the broker's log, wrong-cause in
the user's face.

## Mitigation today, and its expiry

`centralGateway.ingress.enabled` defaults to `false` — in-cluster only. The chart ships a working
Ingress template, so it is one values flip from public. The BOARD's phrasing for
`approval-bypass-bpmn-runner` applies verbatim: **that mitigation does not travel to the work
cluster.**

## What this strengthens

`undeclared-routes` ruled on a set of platform routes. This is the **first cross-repo instance of
the same pattern**, which is evidence the ruling should be read as a standing rule rather than a
one-time disposition of twelve known routes — the pattern is not platform-confined.

## Related

`[[dag-tools-gateway-unverified-subject]]` — the *same file's* main data route never verifies its
bearer and takes its authz subject from a header. Filed separately because it is a different
property (confidentiality vs integrity) on a different route, but the two share a remediation
window and a single question: **what is allowed to talk to this gateway, and how does it prove it?**

## Acceptance

- `/api/v1/internal/register` and `/api/v1/internal/resolve` require an authenticated caller,
  witnessed by an unauthenticated attempt being refused.
- A gate class is recorded for both, citing the `undeclared-routes` precedent.
- The TTL-expiry outage mode has a named detection — something that distinguishes "no broker
  registered" from "broker cannot register", since today both present as 404.
