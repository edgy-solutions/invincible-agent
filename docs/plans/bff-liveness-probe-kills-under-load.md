---
id:         bff-liveness-probe-kills-under-load
status:     open
owner:      unassigned
blocked-on:
closed-by:
code-site:  helm/invincible-agent/values.yaml, src/iagent/gateway.py
repo:       invincible-agent
summary:    ⚠️ DEMO RISK, classified 2026-08-22, SCOPE CORRECTED the same day: this is CHART-WIDE, not one service. 16 of 27 deployments carry `timeoutSeconds: 1` on LIVENESS — every engine, the BFF, the registrar, the projector. Most engines pair it with `readiness: 10`, so someone already judged 1s too tight for readiness and did not carry that to the check that KILLS — the inversion is the finding. Two observed failing so far (BFF SIGKILLed exit 137; Engine DA flapping); the other fourteen have not been under load yet. cortex-bff was SIGKILLed (exit 137) under ordinary traffic — not OOM, a LIVENESS PROBE KILL. The probe allows `/health` `timeoutSeconds: 1` with `failureThreshold: 3`; kubelet recorded "Liveness probe failed x4 over 105m" and "Readiness probe failed x6" with `context deadline exceeded`. A single-threaded FastAPI event loop busy with an Electric shape proxy or a graph query cannot always answer within one second, so the BFF is killed for being busy. In a demo this is every answer failing at once with nothing in the log to point at — the container dies without writing a reason.
---

# The BFF is killed for being busy, and it dies without saying so

Found while chasing why a registration's logs were missing: the pod had restarted, and the
logs were in the *previous* container.

## Classified, not guessed

```
Last State:  Terminated    Reason: Error    Exit Code: 137
Started:  11:03:05   Finished:  11:03:04 (prev)   Restart Count: 1
Limits:   cpu 500m   memory 512Mi

Events:
  Warning  Unhealthy  Readiness probe failed (x6 over 105m): context deadline exceeded
  Warning  Unhealthy  Liveness  probe failed (x4 over 105m): context deadline exceeded

livenessProbe: { path: /health, timeoutSeconds: 1, periodSeconds: 10, failureThreshold: 3 }
```

Exit 137 is SIGKILL. **It is not OOM** — an OOM kill reports `Reason: OOMKilled`, and memory
never appears in the events. The kubelet killed it because `/health` did not answer within one
second, three polls running.

## Why one second is the wrong budget here

`/health` is served by the same single-threaded event loop that proxies Electric shapes,
serves review batches, and issues graph queries. A slow upstream or a burst of shape traffic
blocks the loop, and a blocked loop cannot answer a health check no matter how trivial the
handler is. **The probe is measuring event-loop availability and calling it liveness.**

The readiness failures (x6) are the same cause showing up earlier and more often — the service
was flapping out of the Service's endpoint list before it was ever killed.

## Why this matters more than its size

In a demo the BFF is on the path of every answer. A restart is ~seconds of total failure, and
the container **writes nothing about why** — the last lines before death are ordinary 200s.
Someone debugging live sees answers stop and a healthy-looking log. The reason exists only in
`kubectl describe`, which is not where anyone looks first.

This is also why a registration's rejection log went missing for twenty minutes of
investigation today: the evidence was in the previous container, and nothing in the current
one hinted that a previous container existed.

## SECOND SCOPE CORRECTION 2026-08-22 — 6, not 16, and the engines already solved it

**My first correction was wrong in the other direction.** I surveyed `timeoutSeconds <= 1` and
counted 16 deployments, including every engine. That measured a PROXY, not the property.

`templates/engines.yaml` uses a **TCP** liveness probe, with the reasoning already written down
in the template:

> *"Liveness uses a TCP probe to avoid re-killing the pod for a slow /health response during a
> transient loop hiccup; only a true port loss restarts the container."*

A 1-second TCP connect is fine — it never asks the event loop to answer anything. A 1-second
**HTTP** health check is the defect. Re-surveyed on the real property — *liveness that is
`httpGet` with a timeout ≤ 2s* — the population is **6**:

```
iagent-cortex-bff          ← the one actually killed (exit 137)
iagent-mesh-registrar
iagent-projector
iagent-electric
iagent-dagster-webserver
datahub-datahub-frontend   ← third-party chart, not ours to change
```

**Five are ours.** The engines are already correct and have been; someone reasoned this through
for them and the reasoning never propagated to the services outside `engines.yaml`.

So the fix is not a new default to invent — it is **the engines' existing pattern, applied to
the five that never got it.** That is a smaller, better-evidenced change than the chart-wide
sweep I proposed an hour ago, and it copies a decision this repo already made rather than
making a second one.

**The lesson is mine and it is the session's recurring one:** I measured `timeoutSeconds` and
called it "the probe defect," when the defect is *what the probe asks of a busy process*. A
count over the wrong predicate produced a population 2.7× too large — and would have had me
"fixing" eleven deployments that were already right, including by replacing a deliberate design
with my own.

## SUPERSEDED — first scope correction, kept for the record

Surveyed after a second service showed the identical symptom. **16 of 27 deployments carry a
`timeoutSeconds: 1` liveness probe**, including EVERY engine:

```
cortex-bff, central-gateway, data-analyst, mesh-registrar, projector, electric,
engine-a, engine-d, engine-e, engine-f, engine-o, engine-w,
dagster-webserver, redis, topaz, datahub-frontend
```

So this packet was mis-titled. It is not "the BFF has a bad probe" — it is **any workload in
this chart is killed for being busy for one second**. Two have been observed doing it (the BFF
was SIGKILLed; Engine DA flaps with `context deadline exceeded`); the other fourteen have
simply not been under load yet. A defect that has surfaced twice in a population of sixteen is
not two incidents.

**The pattern inside the numbers is the tell.** Most engines carry `readiness: 10` and
`liveness: 1` — someone already concluded that one second was too tight for readiness and did
not carry the conclusion to liveness. **The stricter budget is on the check that KILLS**, which
is exactly backwards: an unready service is removed from a load balancer and recovers by
itself; a failed liveness probe destroys the process and whatever it was doing.

That inversion is the finding. It makes the fix a single chart-wide default rather than a
per-service patch, and it is cheaper than either service's individual repair.

## Disposal

1. **Raise `timeoutSeconds` to 5 and `failureThreshold` to 3–5.** Smallest change; matches what
   the endpoint actually is. A genuinely wedged service still dies, just not a busy one.
2. **Give `/health` its own budget** — keep it dependency-free and never let it await an
   upstream, so it measures the process rather than its neighbours.
3. **Consider `startupProbe`** so `initialDelaySeconds: 30` stops doing double duty.

Do NOT simply remove the probe: a wedged BFF that stays in the endpoint list is worse than one
that restarts.

## Acceptance

An hour of ordinary sandbox traffic with zero `Unhealthy` events on the deployment, confirmed
by `kubectl describe`. Restart count stable, checked twice with a gap — a single reading of a
restart counter says nothing about whether it is still climbing.
