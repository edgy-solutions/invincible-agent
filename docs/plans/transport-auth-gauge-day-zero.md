---
id:         transport-gauge
status:     closed
owner:      agent
blocked-on: 
closed-by:  e18b5cf
repo:       invincible-agent
summary:    Gauge reads only migratable callers: probe paths exempt, 549 -> 22 -> 0-new-unverified.
---

# Transport-auth gauge — day zero

> ## SUPERSEDED READING (2026-08-08, after SDK v0.2.2) — **22 / 0 verified / 22 unverified**
>
> The reading below (549) was taken before probe paths were exempt and is **kept as the
> before-picture, not as the odometer's start**. After exempting kubelet paths in the SDK and
> the registrar's `/v1/healthz` in the chart, the gauge is pure signal:
>
> | | 2026-08-08 (before exemption) | 2026-08-08 (after) |
> |---|---:|---:|
> | gauge lines, fleet | 549 | **22** |
> | verified | 0 | 0 |
> | unverified | 549 | **22** |
> | of which probe traffic | ~527 | **0** |
>
> **All 22 are `path=/v1/register`, reason `absent, no mint attempted`** — engines
> self-registering with no Authorization header, on nine of ten services silent. This is the
> contract phase's entire remaining population, and it is now countable *because* the
> instrument stopped counting things that can never migrate.
>
> **The flip's precondition is now satisfiable.** "Zero unverified on non-exempt paths" is a
> number that can actually reach zero: 22 → 0 as the registration caller mints. Before the
> exemption it could not, since probes kept it permanently nonzero — an unsatisfiable
> precondition being one that eventually gets waived.
>
> Verified live under REQUIRE on a throwaway pod behind no Service (image `33e9dd8`):
> `/health` no token → **200**; `/query_knowledge` no token → **401**; garbage bearer → **403**
> (`invalid: DecodeError`); minted `svc:supervisor` → past the gate (502 from Restate, a
> *handler* failure); and with `TRANSPORT_AUTH_EXEMPT_PATHS=/v1/healthz`, `/health` → **401**,
> confirming replace-not-extend on the real image.
>
> **OPEN — found by that same witness:** `/openapi.json`, `/docs` and `/redoc` return **200
> unauthenticated even under REQUIRE**. FastAPI registers them via Starlette's `add_route`, not
> `add_api_route`, so app-level `dependencies=` never applies. The endpoint-gating manifest's
> claim that the app-level dependency "covers every route" is therefore **false for three routes
> on all twelve services**. Information disclosure (full API surface enumerable), not data
> access. Needs a ruling: disable docs in deployed images, or gate them in the SDK's factory.
>
> **OPEN — the litany's leg 5 is currently vacuous.** It probes `/health`, which is now exempt,
> so it reads 0 for every service and can no longer fail. My own instrument, broken by my own
> fix — the guard-gone-quiet species. It needs a non-exempt probe path per service before it
> counts as a check again.


**Taken 2026-08-08, immediately after the OBSERVE roll completed** (invincible-agent `24c038a`,
iagent-mesh-sdk `v0.2.1`, sandbox cluster `edge` / namespace `sandbox`).

Recorded now because it is only cheap today: the contract flip's story will want to cite "the
count started at N and fell to zero", and N is unrecoverable once traffic mixes.

## The reading

| service | gauge lines | verified | unverified |
|---|---:|---:|---:|
| engine-o | 48 | 0 | 48 |
| engine-a | 50 | 0 | 50 |
| engine-d | 54 | 0 | 54 |
| engine-e | 54 | 0 | 54 |
| engine-f | 53 | 0 | 53 |
| engine-w | 50 | 0 | 50 |
| data-analyst | 57 | 0 | 57 |
| mesh-registrar | 121 | 0 | 121 |
| projector | 53 | 0 | 53 |
| domain-broker | 9 | 0 | 9 |
| **FLEET** | **549** | **0** | **549** |

Every line reads `caller: none (absent, no mint attempted)`. Not one caller in the sandbox
currently mints.

`engine-b` / `engine-c` exist in source and are **not deployed here**, so the 12-service source
population maps to 10 running workloads. The gauge covers what runs.

## STOP — the flip would take the fleet down today

**The overwhelming majority of this traffic is Kubernetes probes.** Path breakdown:

```
engine-o        51  path=/health
projector       57  path=/health
mesh-registrar  59  path=/health   47 path=/v1/register   19 path=/v1/healthz
```

`transport_auth` is applied as an **app-level FastAPI dependency**, so it covers `/health` too.
The kubelet does not send a bearer token and never will. Under `REQUIRE_TRANSPORT_AUTH`:

1. every liveness/readiness probe gets **401**,
2. every pod is marked unhealthy,
3. the fleet restarts itself into a **cluster-wide outage** — caused by the security control,
   not by an attacker.

This is not a subtle risk; it is the arithmetic of the table above. **The contract phase cannot
flip until probe paths are exempt.**

Note the second-order trap: because probes dominate, **the unverified count can never reach
zero**, so the flip's own precondition is unsatisfiable as currently defined. A gauge that
cannot reach its target is a gauge that will eventually be overridden by someone who decides
the number "doesn't really count" — which is how a precondition becomes a formality.

## The real signal, once probes are set aside

`mesh-registrar` shows **47 unverified `/v1/register` calls** — engines self-registering at
startup with no Authorization header. That is genuine mesh traffic from real callers, and it is
the actual work of the contract phase: those callers must mint. It is legible only because the
probe traffic can be separated from it, which is the argument for fixing the gauge's definition
rather than merely its exemptions.

## What the contract phase needs before any flip

1. **Exempt probe paths** from the transport-auth dependency (`/health`, `/v1/healthz`, and any
   other kubelet-reachable route) — per-route dependency, or a path skip-list in the SDK
   dependency. This is a change to `iagent_mesh.transport_auth`, i.e. one implementation, one
   bump.
2. **Redefine the gauge** to count only non-probe paths, so "reads zero" is reachable and means
   what it says.
3. **Make `/v1/register` callers mint** — engine self-registration is the first real
   unverified-caller population, 47 calls at day zero.
4. Re-take this reading after (1)–(3) and compare. The delta is the migration's actual progress;
   today's 549 is mostly noise the instrument should never have been counting.

## Provenance of this reading

Every service was rolled through the six-leg litany and passed: rollout, digest changed, code
present **in the container** (`iagent-mesh 0.2.1`, `provenance-telemetry 0.1.0`), startup
announcement, per-request gauge line, and — on engine-w — a Langfuse trace join at the
deterministic id (`4807af0c4d18ccccf7c9908b80b9c60b`, `engine-w /query_knowledge`).

Leg 5 was additionally shown **able to fail**: with `IAGENT_MESH_LOG_AUTOCONFIG=0` the gauge
went dark (0 lines) while the service still returned 200 and still announced
`transport auth: OBSERVE` — proving legs 4 and 5 are independent, and that an announcement has
never been evidence that the gauge is readable.
