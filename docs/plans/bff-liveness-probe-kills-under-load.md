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

---

## SECOND INSTANCE, 2026-08-28 — the startup window, not the storm

Recorded so the next person seeing a 502 burst at pod-age ~30s reads one line instead of
diagnosing it.

**The probe widening fixed the STORM-INDUCED case** (readiness flapping under load, pod pulled
from the endpoint list, Traefik answering 404 with no CORS headers). **The startup window
remains**, and it is a different shape:

> For roughly **25 seconds after every cortex-bff roll**, `/health` answers 200 while the routes
> that PROXY an upstream do not. Measured 2026-08-28: pod started ~12:10:30, three 502s at
> 12:10:56 on `/plan/state_version` and two Electric shape subscriptions, then clean —
> `/plan/state_version` returning 200 repeatedly from 12:12:59 onward.

**Why it is benign and why it is not nothing.** `/health` is deliberately dependency-free — it
measures the process, not its neighbours (see recommendation 2 above), which is correct and is
exactly what produces the window: the process is genuinely up before `engine-p`, Electric and the
rest are reachable through it. Callers that retry (the plan-version poller, Electric's
subscription logic) recover silently. A caller that does not retry sees a hard 502.

**The tell:** 502s clustered within ~30s of pod start, on PROXY routes only, clearing on their
own. That is this shape. 502s that persist past a minute, or that appear without a recent roll,
are NOT this and deserve a real diagnosis.

**Retired by** recommendation 3 above — a `startupProbe` would hold the pod out of the endpoint
list until its upstreams are reachable, closing the window rather than documenting it. Until then
this is a known shape, not an open defect.

---

## REPRODUCED ON DEMAND 2026-09-03 — and the workload that does it is small

**This item was classified from kubelet events and two opportunistic observations. It is now
reproducible deliberately, which moves it from "seen twice" to "a property of the deployment".**

**The workload: SIX sequential `/orchestrate` calls**, issued back to back by
`tests/sandbox_e2e/mesh_client.py` as `alice`, over about four minutes. Not a load test — six
questions, one after another, which is *less* than a person exploring during a demo.

```
iagent-cortex-bff-856b7d449-q5tfm   restarts=2
lastState.terminated: exitCode 137, reason "Error",
                      startedAt 2026-09-03T03:29:58Z, finishedAt 2026-09-03T13:27:11Z
```

**What it looked like from the caller's side, and this is the part that matters for a demo:**
the first two questions answered. The next four returned `RemoteProtocolError: peer closed
connection without sending complete message body`, then `ReadError`, then `ConnectError: All
connection attempts failed` — **and every one of those is indistinguishable, at the caller,
from the system having nothing to say.** The probe that produced them had no transport control,
so its first pass recorded four "results" that were not measurements at all. A person in a demo
would read the same four as the system failing to answer.

**The tell, for anyone who meets this next:** answers that *degrade in sequence* — a real
answer, then a truncated one, then connection errors — rather than failing uniformly. A busy
event loop dies partway through a run, so the shape is a cliff mid-session, not a flat failure.

**No fix attempted here.** The finding is only that the trigger is far cheaper than "load", and
that the failure reaches the caller wearing an empty answer's clothes. Recorded by the
engine-cost lane while measuring something else entirely.
